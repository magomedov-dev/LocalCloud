import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ItemActions } from "@/components/files/ItemActions";
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

// Изолируем тяжёлые дочерние диалоги, чтобы не тянуть их API-зависимости.
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
  DeleteConfirmDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="delete-dialog" /> : null,
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

function renderActions(item: NodeListItem, props: Partial<Parameters<typeof ItemActions>[0]> = {}) {
  const onColorChange = vi.fn();
  const onPreview = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ItemActions
        item={item}
        folderQueryKey={["nodes", "root"]}
        folderColor={null}
        onColorChange={onColorChange}
        onPreview={onPreview}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onColorChange, onPreview };
}

async function openMenu() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button"));
  return user;
}

describe("ItemActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useFolderDownloadMock.mockReturnValue({ downloadFolder, downloading: null });
  });

  it("показывает действия файла: просмотр, скачать, переименовать, поделиться, информация, удалить", async () => {
    renderActions(file());
    await openMenu();
    expect(screen.getByText("Просмотр")).toBeInTheDocument();
    expect(screen.getByText("Скачать")).toBeInTheDocument();
    expect(screen.getByText("Переименовать")).toBeInTheDocument();
    expect(screen.getByText("Переместить")).toBeInTheDocument();
    expect(screen.getByText("Поделиться")).toBeInTheDocument();
    expect(screen.getByText("Информация")).toBeInTheDocument();
    expect(screen.getByText("Удалить")).toBeInTheDocument();
    // Цвет папки отсутствует для файла
    expect(screen.queryByText("Цвет папки")).not.toBeInTheDocument();
  });

  it("скрывает «Просмотр», если предпросмотр не поддерживается", async () => {
    renderActions(file({ name: "bin.xyz", file_mime_type: "application/octet-stream" }));
    await openMenu();
    expect(screen.queryByText("Просмотр")).not.toBeInTheDocument();
  });

  it("скрывает «Просмотр», если onPreview не передан", async () => {
    renderActions(file(), { onPreview: undefined });
    await openMenu();
    expect(screen.queryByText("Просмотр")).not.toBeInTheDocument();
  });

  it("вызывает onPreview", async () => {
    const { onPreview } = renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Просмотр"));
    expect(onPreview).toHaveBeenCalled();
  });

  it("скачивает файл через downloadNodeFile", async () => {
    renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Скачать"));
    expect(downloadNodeFile).toHaveBeenCalledWith("f1", "doc.txt");
  });

  it("скачивает папку через downloadFolder", async () => {
    renderActions(folder());
    const user = await openMenu();
    await user.click(screen.getByText("Скачать"));
    expect(downloadFolder).toHaveBeenCalledWith("d1", "Папка");
  });

  it("показывает пункт «Цвет папки» для папки и открывает диалог", async () => {
    renderActions(folder());
    const user = await openMenu();
    expect(screen.getByText("Цвет папки")).toBeInTheDocument();
    await user.click(screen.getByText("Цвет папки"));
    expect(screen.getByTestId("color-dialog")).toBeInTheDocument();
  });

  it("открывает диалог переименования", async () => {
    renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Переименовать"));
    expect(screen.getByTestId("rename-dialog")).toBeInTheDocument();
  });

  it("открывает диалог перемещения", async () => {
    renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Переместить"));
    expect(screen.getByTestId("move-dialog")).toBeInTheDocument();
  });

  it("дублирует элемент: copy с текущей папкой без имени и toast success", async () => {
    vi.mocked(nodesApi.copy).mockResolvedValueOnce({});
    renderActions(file({ parent_id: "parent-1" }));
    const user = await openMenu();
    await user.click(screen.getByText("Дублировать"));
    await waitFor(() =>
      expect(nodesApi.copy).toHaveBeenCalledWith("f1", { target_parent_id: "parent-1" }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Дублировано"));
  });

  it("дублирует элемент из корня с target_parent_id null", async () => {
    vi.mocked(nodesApi.copy).mockResolvedValueOnce({});
    renderActions(file({ parent_id: null }));
    const user = await openMenu();
    await user.click(screen.getByText("Дублировать"));
    await waitFor(() =>
      expect(nodesApi.copy).toHaveBeenCalledWith("f1", { target_parent_id: null }),
    );
  });

  it("показывает ошибку, если дублирование не удалось", async () => {
    vi.mocked(nodesApi.copy).mockRejectedValueOnce(new Error("fail"));
    renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Дублировать"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Ошибка копирования"));
  });

  it("открывает диалог копирования в режиме copy", async () => {
    renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Копировать в…"));
    expect(screen.getByTestId("copy-dialog")).toBeInTheDocument();
  });

  it("открывает диалог шаринга", async () => {
    renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Поделиться"));
    expect(screen.getByTestId("share-dialog")).toBeInTheDocument();
  });

  it("открывает диалог удаления", async () => {
    renderActions(file());
    const user = await openMenu();
    await user.click(screen.getByText("Удалить"));
    expect(screen.getByTestId("delete-dialog")).toBeInTheDocument();
  });

  it("вызывает openInfo с элементом", async () => {
    const item = file();
    renderActions(item);
    const user = await openMenu();
    await user.click(screen.getByText("Информация"));
    expect(openInfo).toHaveBeenCalledWith(item);
  });

  it("блокирует скачивание папки во время загрузки", async () => {
    useFolderDownloadMock.mockReturnValue({ downloadFolder, downloading: "d1" });
    renderActions(folder());
    await openMenu();
    expect(screen.getByText("Скачать").closest("[role='menuitem']")).toHaveAttribute(
      "data-disabled",
    );
  });

  it("прокидывает изменение состояния меню через onOpenChange", async () => {
    const onOpenChange = vi.fn();
    renderActions(file(), { onOpenChange });
    await openMenu();
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });
});
