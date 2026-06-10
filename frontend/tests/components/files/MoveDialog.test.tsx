import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import { MoveDialog } from "@/components/files/MoveDialog";
import { nodesApi } from "@/api/nodes";
import type { NodeListItem } from "@/types/nodes";

vi.mock("@/api/nodes", () => ({
  nodesApi: { list: vi.fn(), content: vi.fn(), move: vi.fn() },
}));

vi.mock("@/lib/folderCache", () => ({
  optimisticallyRemoveNodes: vi.fn(() => vi.fn()),
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
  friendlyError: vi.fn(() => "Ошибка перемещения"),
}));

import { toast } from "sonner";
import { optimisticallyRemoveNodes } from "@/lib/folderCache";

const mockList = vi.mocked(nodesApi.list);
const mockContent = vi.mocked(nodesApi.content);
const mockMove = vi.mocked(nodesApi.move);

function folder(id: string, name: string): NodeListItem {
  return {
    id,
    owner_id: "o",
    parent_id: null,
    name,
    node_type: "folder",
    visibility: "private",
    path: `/${name}`,
    depth: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_deleted: false,
  };
}

function renderDialog(props: Partial<Parameters<typeof MoveDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  const onMoved = vi.fn();
  const utils = renderWithProviders(
    <MoveDialog
      open
      onOpenChange={onOpenChange}
      nodeIds={["a"]}
      label="файл.txt"
      folderQueryKey={["nodes", "root"]}
      onMoved={onMoved}
      {...props}
    />,
  );
  return { onOpenChange, onMoved, ...utils };
}

describe("MoveDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue({ items: [folder("f1", "Документы"), folder("f2", "Картинки")] } as never);
    mockContent.mockResolvedValue({ items: [folder("f3", "Вложенная")] } as never);
    mockMove.mockResolvedValue({});
  });

  it("показывает корневые папки, исключая перемещаемые элементы", async () => {
    renderDialog({ nodeIds: ["f1"] });
    expect(await screen.findByText("Картинки")).toBeInTheDocument();
    // f1 исключён, поскольку входит в перемещаемые
    expect(screen.queryByText("Документы")).not.toBeInTheDocument();
  });

  it("отображает заголовок для одного элемента", async () => {
    renderDialog({ nodeIds: ["a"], label: "файл.txt" });
    expect(screen.getByText("Переместить «файл.txt»")).toBeInTheDocument();
    await screen.findByText("Документы");
  });

  it("отображает заголовок для нескольких элементов", async () => {
    renderDialog({ nodeIds: ["a", "b"], label: "2 элемента" });
    expect(screen.getByText("Переместить 2 элемента")).toBeInTheDocument();
    await screen.findByText("Документы");
  });

  it("показывает «Нет папок», когда папок нет", async () => {
    mockList.mockResolvedValue({ items: [] } as never);
    renderDialog();
    expect(await screen.findByText("Нет папок")).toBeInTheDocument();
  });

  it("навигирует в папку и подгружает её содержимое", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByText("Документы"));
    expect(await screen.findByText("Вложенная")).toBeInTheDocument();
    expect(mockContent).toHaveBeenCalledWith("f1");
  });

  it("перемещает в корень: вызывает move для каждого id, toast success и onMoved", async () => {
    const user = userEvent.setup();
    const { onMoved, onOpenChange } = renderDialog({ nodeIds: ["a", "b"], label: "2 элемента" });
    await screen.findByText("Документы");

    await user.click(screen.getByRole("button", { name: "Переместить сюда" }));

    await waitFor(() => expect(mockMove).toHaveBeenCalledTimes(2));
    expect(mockMove).toHaveBeenCalledWith("a", { target_parent_id: null });
    expect(mockMove).toHaveBeenCalledWith("b", { target_parent_id: null });
    expect(optimisticallyRemoveNodes).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Перемещено 2 элементов"));
    expect(onMoved).toHaveBeenCalled();
  });

  it("перемещает один элемент в выбранную папку с целевым parent id", async () => {
    const user = userEvent.setup();
    renderDialog({ nodeIds: ["a"], label: "файл.txt" });
    await user.click(await screen.findByText("Документы"));
    await screen.findByText("Вложенная");

    await user.click(screen.getByRole("button", { name: "Переместить сюда" }));

    await waitFor(() =>
      expect(mockMove).toHaveBeenCalledWith("a", { target_parent_id: "f1" }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("«файл.txt» перемещено"));
  });

  it("при частичной ошибке показывает счётчик неудач", async () => {
    const user = userEvent.setup();
    mockMove.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("fail"));
    renderDialog({ nodeIds: ["a", "b"], label: "2 элемента" });
    await screen.findByText("Документы");

    await user.click(screen.getByRole("button", { name: "Переместить сюда" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось переместить 1 из 2 элементов"),
    );
  });

  it("при полной ошибке откатывает и показывает причину", async () => {
    const rollback = vi.fn();
    vi.mocked(optimisticallyRemoveNodes).mockReturnValue(rollback);
    mockMove.mockRejectedValue(new Error("conflict"));
    const user = userEvent.setup();
    renderDialog({ nodeIds: ["a"], label: "файл.txt" });
    await screen.findByText("Документы");

    await user.click(screen.getByRole("button", { name: "Переместить сюда" }));

    await waitFor(() => expect(rollback).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalledWith("Ошибка перемещения");
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("закрывает диалог по кнопке «Отмена»", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await screen.findByText("Документы");
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("возвращается на верхний уровень по хлебным крошкам", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByText("Документы"));
    await screen.findByText("Вложенная");
    // Кликаем по корню «Файлы» в хлебных крошках
    const crumbs = screen.getByText("Файлы");
    await user.click(crumbs);
    expect(await screen.findByText("Документы")).toBeInTheDocument();
  });
});
