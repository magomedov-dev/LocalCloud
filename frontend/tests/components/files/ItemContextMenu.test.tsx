import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import { ItemContextMenu } from "@/components/files/ItemContextMenu";
import { nodesApi } from "@/api/nodes";
import { toast } from "sonner";
import type { NodeListItem } from "@/types/nodes";

vi.mock("@/api/nodes", () => ({
  nodesApi: { copy: vi.fn() },
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
  friendlyError: vi.fn(() => "Ошибка копирования"),
}));

vi.mock("@/components/files/RenameDialog", () => ({
  RenameDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="rename-dialog" /> : null,
}));
vi.mock("@/components/files/MoveDialog", () => ({
  MoveDialog: ({ open, mode }: { open: boolean; mode?: "move" | "copy" }) =>
    open ? <div data-testid={mode === "copy" ? "copy-dialog" : "move-dialog"} /> : null,
}));
vi.mock("@/components/files/ShareDialog", () => ({
  ShareDialog: ({ open }: { open: boolean }) => (open ? <div data-testid="share-dialog" /> : null),
}));
vi.mock("@/components/files/FolderColorDialog", () => ({
  FolderColorDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="color-dialog" /> : null,
}));
vi.mock("@/components/files/DeleteConfirmDialog", () => ({
  DeleteConfirmDialog: ({ open, items }: { open: boolean; items: NodeListItem[] }) =>
    open ? <div data-testid="delete-dialog" data-count={items.length} /> : null,
}));

const downloadFolder = vi.fn();
const useFolderDownloadMock = vi.fn(() => ({ downloadFolder, downloading: null as string | null }));
vi.mock("@/hooks/useFolderDownload", () => ({
  useFolderDownload: () => useFolderDownloadMock(),
}));

const openInfo = vi.fn();
vi.mock("@/contexts/infoPanel-context", () => ({
  useInfoPanel: () => ({ openInfo, closeInfo: vi.fn(), selectedItem: null }),
}));

const downloadNodeFile = vi.fn();
vi.mock("@/lib/download", () => ({
  downloadNodeFile: (...args: unknown[]) => downloadNodeFile(...args),
}));

const navigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigate };
});

function file(overrides: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: "f1",
    owner_id: "o",
    parent_id: null,
    name: "doc.txt",
    node_type: "file",
    visibility: "private",
    path: "/doc.txt",
    depth: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_deleted: false,
    file_mime_type: "text/plain",
    ...overrides,
  };
}

function folder(overrides: Partial<NodeListItem> = {}): NodeListItem {
  return file({ id: "d1", name: "Папка", node_type: "folder", file_mime_type: null, ...overrides });
}

function renderMenu(item: NodeListItem, props: Partial<Parameters<typeof ItemContextMenu>[0]> = {}) {
  const onColorChange = vi.fn();
  const onPreview = vi.fn();
  const onSelect = vi.fn();
  renderWithProviders(
    <ItemContextMenu
      item={item}
      folderQueryKey={["nodes", "root"]}
      folderColor={null}
      onColorChange={onColorChange}
      onPreview={onPreview}
      onSelect={onSelect}
      {...props}
    >
      <div data-testid="trigger">target</div>
    </ItemContextMenu>,
  );
  return { onColorChange, onPreview, onSelect };
}

async function openMenu() {
  const user = userEvent.setup();
  await user.pointer({ keys: "[MouseRight]", target: screen.getByTestId("trigger") });
  return user;
}

describe("ItemContextMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useFolderDownloadMock.mockReturnValue({ downloadFolder, downloading: null });
  });

  it("показывает действия файла", async () => {
    renderMenu(file());
    await openMenu();
    expect(screen.getByText("Просмотр")).toBeInTheDocument();
    expect(screen.getByText("Скачать")).toBeInTheDocument();
    expect(screen.getByText("Переименовать")).toBeInTheDocument();
    expect(screen.getByText("Поделиться")).toBeInTheDocument();
    expect(screen.getByText("Информация")).toBeInTheDocument();
    expect(screen.getByText("Удалить")).toBeInTheDocument();
    expect(screen.queryByText("Открыть")).not.toBeInTheDocument();
    expect(screen.queryByText("Цвет папки")).not.toBeInTheDocument();
  });

  it("показывает «Открыть» и «Цвет папки» для папки", async () => {
    renderMenu(folder());
    await openMenu();
    expect(screen.getByText("Открыть")).toBeInTheDocument();
    expect(screen.getByText("Цвет папки")).toBeInTheDocument();
    expect(screen.queryByText("Просмотр")).not.toBeInTheDocument();
  });

  it("навигирует в папку при клике «Открыть»", async () => {
    renderMenu(folder());
    const user = await openMenu();
    await user.click(screen.getByText("Открыть"));
    expect(navigate).toHaveBeenCalledWith("/files/folders/d1");
  });

  it("скачивает файл напрямую", async () => {
    renderMenu(file());
    const user = await openMenu();
    await user.click(screen.getByText("Скачать"));
    expect(downloadNodeFile).toHaveBeenCalledWith("f1", "doc.txt");
  });

  it("скачивает папку через downloadFolder", async () => {
    renderMenu(folder());
    const user = await openMenu();
    await user.click(screen.getByText("Скачать"));
    expect(downloadFolder).toHaveBeenCalledWith("d1", "Папка");
  });

  it("вызывает onPreview", async () => {
    const { onPreview } = renderMenu(file());
    const user = await openMenu();
    await user.click(screen.getByText("Просмотр"));
    expect(onPreview).toHaveBeenCalled();
  });

  it("открывает диалоги переименования, перемещения, шаринга и удаления", async () => {
    renderMenu(file());
    let user = await openMenu();
    await user.click(screen.getByText("Переименовать"));
    expect(screen.getByTestId("rename-dialog")).toBeInTheDocument();

    user = await openMenu();
    await user.click(screen.getByText("Переместить"));
    expect(screen.getByTestId("move-dialog")).toBeInTheDocument();

    user = await openMenu();
    await user.click(screen.getByText("Поделиться"));
    expect(screen.getByTestId("share-dialog")).toBeInTheDocument();

    user = await openMenu();
    await user.click(screen.getByText("Удалить"));
    expect(screen.getByTestId("delete-dialog")).toBeInTheDocument();
  });

  it("дублирует элемент: copy с текущей папкой без имени и toast success", async () => {
    vi.mocked(nodesApi.copy).mockResolvedValueOnce({});
    renderMenu(file({ parent_id: "parent-1" }));
    const user = await openMenu();
    await user.click(screen.getByText("Дублировать"));
    await waitFor(() =>
      expect(nodesApi.copy).toHaveBeenCalledWith("f1", { target_parent_id: "parent-1" }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Дублировано"));
  });

  it("показывает ошибку, если дублирование не удалось", async () => {
    vi.mocked(nodesApi.copy).mockRejectedValueOnce(new Error("fail"));
    renderMenu(file());
    const user = await openMenu();
    await user.click(screen.getByText("Дублировать"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Ошибка копирования"));
  });

  it("открывает диалог копирования в режиме copy", async () => {
    renderMenu(file());
    const user = await openMenu();
    await user.click(screen.getByText("Копировать в…"));
    expect(screen.getByTestId("copy-dialog")).toBeInTheDocument();
  });

  it("открывает диалог цвета папки", async () => {
    renderMenu(folder());
    const user = await openMenu();
    await user.click(screen.getByText("Цвет папки"));
    expect(screen.getByTestId("color-dialog")).toBeInTheDocument();
  });

  it("вызывает openInfo с элементом", async () => {
    const item = file();
    renderMenu(item);
    const user = await openMenu();
    await user.click(screen.getByText("Информация"));
    expect(openInfo).toHaveBeenCalledWith(item);
  });

  it("выбирает элемент при открытии меню на невыбранном", async () => {
    const item = file();
    const { onSelect } = renderMenu(item, { isSelected: false });
    await openMenu();
    expect(onSelect).toHaveBeenCalledWith(item, { ctrl: false, shift: false });
  });

  it("не вызывает onSelect, если элемент уже выбран", async () => {
    const { onSelect } = renderMenu(file(), { isSelected: true });
    await openMenu();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("передаёт весь выбор в диалог удаления при множественном выделении", async () => {
    const item = file();
    const selectedItems = [item, file({ id: "f2" }), file({ id: "f3" })];
    renderMenu(item, { isSelected: true, selectedItems });
    const user = await openMenu();
    await user.click(screen.getByText("Удалить"));
    expect(screen.getByTestId("delete-dialog")).toHaveAttribute("data-count", "3");
  });
});
