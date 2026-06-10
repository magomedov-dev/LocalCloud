import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { FileMultiActionBar } from "./FileMultiActionBar";
import { nodesApi } from "@/api/nodes";
import type { NodeListItem } from "@/types/nodes";

vi.mock("@/api/nodes", () => ({
  nodesApi: { softDelete: vi.fn() },
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

// MoveDialog рендерится как дочерний; подменяем его, чтобы изолировать тест.
vi.mock("./MoveDialog", () => ({
  MoveDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="move-dialog" /> : null,
}));

const downloadItems = vi.fn();
const useBulkDownloadMock = vi.fn(() => ({
  downloadItems,
  active: false,
  status: "",
  progress: 0,
}));
vi.mock("@/hooks/useBulkDownload", () => ({
  useBulkDownload: () => useBulkDownloadMock(),
}));

const closeInfo = vi.fn();
const useInfoPanelMock = vi.fn(() => ({
  selectedItem: null as NodeListItem | null,
  openInfo: vi.fn(),
  closeInfo,
}));
vi.mock("@/contexts/infoPanel-context", () => ({
  useInfoPanel: () => useInfoPanelMock(),
}));

import { toast } from "sonner";
import { removeNodesFromFolderCache } from "@/lib/folderCache";

const mockSoftDelete = vi.mocked(nodesApi.softDelete);

function item(id: string, name = `item-${id}`): NodeListItem {
  return {
    id,
    owner_id: "o",
    parent_id: null,
    name,
    node_type: "file",
    visibility: "private",
    path: `/${name}`,
    depth: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_deleted: false,
  };
}

function renderBar(items: NodeListItem[]) {
  const onDeselect = vi.fn();
  const utils = renderWithProviders(
    <FileMultiActionBar
      items={items}
      folderQueryKey={["nodes", "root"]}
      onDeselect={onDeselect}
    />,
  );
  return { onDeselect, ...utils };
}

describe("FileMultiActionBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useBulkDownloadMock.mockReturnValue({
      downloadItems,
      active: false,
      status: "",
      progress: 0,
    });
    useInfoPanelMock.mockReturnValue({ selectedItem: null, openInfo: vi.fn(), closeInfo });
    mockSoftDelete.mockResolvedValue({});
  });

  it("показывает количество элементов с правильной множественной формой", () => {
    renderBar([item("1")]);
    expect(screen.getByText(/1 элемент/)).toBeInTheDocument();
  });

  it("показывает форму «элемента» для 2-4 элементов", () => {
    renderBar([item("1"), item("2")]);
    expect(screen.getByText(/2 элемента/)).toBeInTheDocument();
  });

  it("показывает форму «элементов» для 5+ элементов", () => {
    renderBar([item("1"), item("2"), item("3"), item("4"), item("5")]);
    expect(screen.getByText(/5 элементов/)).toBeInTheDocument();
  });

  it("снимает выделение по кнопке", async () => {
    const user = userEvent.setup();
    const { onDeselect } = renderBar([item("1")]);
    await user.click(screen.getByRole("button", { name: "Снять выделение" }));
    expect(onDeselect).toHaveBeenCalled();
  });

  it("запускает скачивание выбранных элементов", async () => {
    const user = userEvent.setup();
    const items = [item("1"), item("2")];
    renderBar(items);
    await user.click(screen.getByTitle("Скачать"));
    expect(downloadItems).toHaveBeenCalledWith(items);
  });

  it("показывает прогресс при активном скачивании", () => {
    useBulkDownloadMock.mockReturnValue({
      downloadItems,
      active: true,
      status: "Архивация…",
      progress: 42,
    });
    renderBar([item("1")]);
    expect(screen.getByText("Архивация…")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("открывает диалог перемещения по кнопке", async () => {
    const user = userEvent.setup();
    renderBar([item("1")]);
    await user.click(screen.getByTitle("Переместить"));
    expect(screen.getByTestId("move-dialog")).toBeInTheDocument();
  });

  it("удаляет все элементы: softDelete, обновление кеша, onDeselect, success", async () => {
    const user = userEvent.setup();
    const { onDeselect } = renderBar([item("1"), item("2")]);

    await user.click(screen.getByTitle("Удалить"));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(mockSoftDelete).toHaveBeenCalledTimes(2));
    expect(removeNodesFromFolderCache).toHaveBeenCalledWith(
      expect.anything(),
      ["nodes", "root"],
      ["1", "2"],
    );
    expect(onDeselect).toHaveBeenCalled();
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("2 элемента перемещено в корзину"));
  });

  it("при частичной ошибке удаления показывает счётчик неудач", async () => {
    const user = userEvent.setup();
    mockSoftDelete.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("fail"));
    renderBar([item("1"), item("2")]);

    await user.click(screen.getByTitle("Удалить"));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось переместить 1 из 2 элементов в корзину"),
    );
  });

  it("при полной ошибке удаления показывает причину и не трогает кеш", async () => {
    const user = userEvent.setup();
    mockSoftDelete.mockRejectedValue(new Error("denied"));
    const { onDeselect } = renderBar([item("1")]);

    await user.click(screen.getByTitle("Удалить"));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Ошибка удаления"));
    expect(removeNodesFromFolderCache).not.toHaveBeenCalled();
    expect(onDeselect).not.toHaveBeenCalled();
  });

  it("закрывает инфо-панель удалённого элемента", async () => {
    const user = userEvent.setup();
    useInfoPanelMock.mockReturnValue({
      selectedItem: item("1"),
      openInfo: vi.fn(),
      closeInfo,
    });
    renderBar([item("1")]);

    await user.click(screen.getByTitle("Удалить"));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(closeInfo).toHaveBeenCalled());
  });

  it("отменяет удаление в диалоге подтверждения", async () => {
    const user = userEvent.setup();
    renderBar([item("1")]);
    await user.click(screen.getByTitle("Удалить"));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Отмена" }));
    expect(mockSoftDelete).not.toHaveBeenCalled();
  });
});
