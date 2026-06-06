import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import type { NodeListItem } from "@/types/nodes";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

const openInfo = vi.fn();
vi.mock("@/contexts/infoPanel-context", () => ({
  useInfoPanel: () => ({ openInfo, selectedItem: null, closeInfo: vi.fn() }),
}));

const downloadFolder = vi.fn();
let downloadingId: string | null = null;
vi.mock("@/hooks/useFolderDownload", () => ({
  useFolderDownload: () => ({ downloadFolder, downloading: downloadingId }),
}));

const downloadNodeFile = vi.fn<(...args: unknown[]) => Promise<void>>(() =>
  Promise.resolve(),
);
vi.mock("@/lib/download", () => ({
  downloadNodeFile: (...a: unknown[]) => downloadNodeFile(...a),
}));

vi.mock("@/components/files/folderColors", () => ({
  getFolderColor: vi.fn(() => "#123456"),
}));

vi.mock("@/components/files/FileIcon", () => ({
  FileIcon: () => <span data-testid="file-icon" />,
}));

// Stub heavy child dialogs to surface their open state.
vi.mock("@/components/files/RenameDialog", () => ({
  RenameDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="rename-dialog" /> : null,
}));
vi.mock("@/components/files/MoveDialog", () => ({
  MoveDialog: ({ open }: { open: boolean }) => (open ? <div data-testid="move-dialog" /> : null),
}));
vi.mock("@/components/files/DeleteConfirmDialog", () => ({
  DeleteConfirmDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="delete-dialog" /> : null,
}));
vi.mock("@/components/files/ShareDialog", () => ({
  ShareDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="share-dialog" /> : null,
}));
vi.mock("@/components/files/FolderColorDialog", () => ({
  FolderColorDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="color-dialog" /> : null,
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { FileActionBar } from "@/components/files/FileActionBar";

function renderBar(ui: React.ReactElement) {
  return renderWithProviders(<TooltipProvider>{ui}</TooltipProvider>);
}

/** Finds an action button by the lucide icon class it contains. */
function btnByIcon(container: HTMLElement, iconClass: string): HTMLButtonElement {
  const svg = container.querySelector(`svg.${iconClass}`);
  const btn = svg?.closest("button");
  if (!btn) throw new Error(`button with icon ${iconClass} not found`);
  return btn as HTMLButtonElement;
}

function makeItem(over: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: "item-1",
    owner_id: "o",
    parent_id: null,
    name: "Документ.pdf",
    node_type: "file",
    visibility: "private",
    path: "/x",
    depth: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    is_deleted: false,
    file_size_bytes: 100,
    file_mime_type: "application/pdf",
    ...over,
  };
}

describe("FileActionBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    downloadingId = null;
  });

  it("renders item name and icon", () => {
    renderBar(<FileActionBar item={makeItem()} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    expect(screen.getByText("Документ.pdf")).toBeInTheDocument();
    expect(screen.getByTestId("file-icon")).toBeInTheDocument();
  });

  it("calls onDeselect when X is clicked", async () => {
    const user = userEvent.setup();
    const onDeselect = vi.fn();
    renderBar(<FileActionBar item={makeItem()} folderQueryKey={["k"]} onDeselect={onDeselect} />,
    );
    // First button is the deselect (X) button.
    await user.click(screen.getAllByRole("button")[0]);
    expect(onDeselect).toHaveBeenCalled();
  });

  it("does not show 'open' action for files", () => {
    const { container } = renderBar(
      <FileActionBar item={makeItem()} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    expect(container.querySelector("svg.lucide-folder-open")).toBeNull();
  });

  it("downloads a file via downloadNodeFile", async () => {
    const user = userEvent.setup();
    const { container } = renderBar(
      <FileActionBar item={makeItem()} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    await user.click(btnByIcon(container, "lucide-download"));
    await waitFor(() => expect(downloadNodeFile).toHaveBeenCalledWith("item-1", "Документ.pdf"));
    expect(downloadFolder).not.toHaveBeenCalled();
  });

  it("downloads a folder via downloadFolder and shows open action", async () => {
    const user = userEvent.setup();
    const folder = makeItem({ node_type: "folder", name: "Папка", file_mime_type: null });
    const { container } = renderBar(
      <FileActionBar item={folder} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    expect(container.querySelector("svg.lucide-folder-open")).not.toBeNull();
    await user.click(btnByIcon(container, "lucide-download"));
    expect(downloadFolder).toHaveBeenCalledWith("item-1", "Папка");
  });

  it("navigates into folder on open", async () => {
    const user = userEvent.setup();
    const folder = makeItem({ node_type: "folder", name: "Папка", file_mime_type: null });
    const { container } = renderBar(
      <FileActionBar item={folder} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    await user.click(btnByIcon(container, "lucide-folder-open"));
    expect(navigate).toHaveBeenCalledWith("/files/folders/item-1");
  });

  it("opens info panel", async () => {
    const user = userEvent.setup();
    const item = makeItem();
    const { container } = renderBar(
      <FileActionBar item={item} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    await user.click(btnByIcon(container, "lucide-info"));
    expect(openInfo).toHaveBeenCalledWith(item);
  });

  it("opens rename dialog", async () => {
    const user = userEvent.setup();
    const { container } = renderBar(
      <FileActionBar item={makeItem()} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    await user.click(btnByIcon(container, "lucide-pencil"));
    expect(screen.getByTestId("rename-dialog")).toBeInTheDocument();
  });

  it("opens delete dialog", async () => {
    const user = userEvent.setup();
    const { container } = renderBar(
      <FileActionBar item={makeItem()} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    await user.click(btnByIcon(container, "lucide-trash-2"));
    expect(screen.getByTestId("delete-dialog")).toBeInTheDocument();
  });

  it("shows folder color option in overflow only for folders", async () => {
    const user = userEvent.setup();
    const folder = makeItem({ node_type: "folder", name: "Папка", file_mime_type: null });
    const { container } = renderBar(
      <FileActionBar item={folder} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    await user.click(btnByIcon(container, "lucide-ellipsis"));
    expect(await screen.findByText("Цвет папки")).toBeInTheDocument();
    expect(await screen.findByText("Переместить")).toBeInTheDocument();
  });

  it("does not show folder color option for files", async () => {
    const user = userEvent.setup();
    const { container } = renderBar(
      <FileActionBar item={makeItem()} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    await user.click(btnByIcon(container, "lucide-ellipsis"));
    expect(await screen.findByText("Поделиться")).toBeInTheDocument();
    expect(screen.queryByText("Цвет папки")).not.toBeInTheDocument();
  });

  it("disables download button while folder is downloading", () => {
    downloadingId = "item-1";
    const folder = makeItem({ node_type: "folder", name: "Папка", file_mime_type: null });
    const { container } = renderBar(
      <FileActionBar item={folder} folderQueryKey={["k"]} onDeselect={vi.fn()} />,
    );
    // While downloading the Download icon is replaced by a spinner (Loader2).
    expect(container.querySelector("svg.lucide-loader-circle")).not.toBeNull();
  });
});
