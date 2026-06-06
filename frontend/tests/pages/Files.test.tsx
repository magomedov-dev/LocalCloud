import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders } from "@tests/utils";
import type { NodeListItem } from "@/types/nodes";

// ── Hook / context mocks ──────────────────────────────────────────────────────

const fileBrowser = {
  data: undefined as unknown,
  isLoading: false,
  error: null as unknown,
  hasNextPage: false,
  isFetchingNextPage: false,
  fetchNextPage: vi.fn(),
};
vi.mock("@/hooks/useFileBrowser", () => ({
  useFileBrowser: () => fileBrowser,
}));

const enqueue = vi.fn();
vi.mock("@/contexts/upload-context", () => ({ useUpload: () => ({ enqueue }) }));

const setCrumbs = vi.fn();
vi.mock("@/contexts/breadcrumb-context", () => ({
  useBreadcrumb: () => ({ setCrumbs }),
}));

const openInfo = vi.fn();
const infoPanel = { selectedItem: null as unknown, openInfo };
vi.mock("@/contexts/infoPanel-context", () => ({
  useInfoPanel: () => infoPanel,
}));

const uploadFolder = vi.fn();
vi.mock("@/hooks/useFolderUpload", () => ({
  useFolderUpload: () => ({ uploadFolder }),
}));

vi.mock("@/api/nodes", () => ({
  nodesApi: { move: vi.fn() },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("@/lib/errors", () => ({ friendlyError: vi.fn(() => "friendly error") }));

// ── Child component stubs ─────────────────────────────────────────────────────

// FileGrid stub exposes buttons to drive selection and drop handlers.
vi.mock("@/components/files/FileGrid", () => ({
  FileGrid: ({
    items,
    isLoading,
    onSelectItem,
    onDrop,
  }: {
    items: NodeListItem[];
    isLoading: boolean;
    onSelectItem: (item: NodeListItem, opts: { ctrl?: boolean; shift?: boolean }) => void;
    onDrop: (draggedId: string, targetFolderId: string) => void;
  }) => {
    if (isLoading) return <div data-testid="grid-loading">loading</div>;
    if (items.length === 0) return <div data-testid="grid-empty">empty</div>;
    return (
      <div data-testid="grid">
        {items.map((it) => (
          <div key={it.id}>
            <button onClick={() => onSelectItem(it, {})}>select-{it.name}</button>
            <button onClick={() => onSelectItem(it, { ctrl: true })}>ctrl-{it.name}</button>
            <button onClick={() => onDrop(it.id, "target-folder")}>drop-{it.name}</button>
          </div>
        ))}
      </div>
    );
  },
}));

vi.mock("@/components/files/FileFilterBar", () => ({
  FileFilterBar: () => <div data-testid="filter-bar" />,
}));
vi.mock("@/components/files/FileActionBar", () => ({
  FileActionBar: ({ item }: { item: NodeListItem }) => (
    <div data-testid="action-bar">action:{item.name}</div>
  ),
}));
vi.mock("@/components/files/FileMultiActionBar", () => ({
  FileMultiActionBar: ({ items }: { items: NodeListItem[] }) => (
    <div data-testid="multi-action-bar">multi:{items.length}</div>
  ),
}));
vi.mock("@/components/files/DropZone", () => ({
  DropZone: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/components/files/CreateFolderDialog", () => ({
  CreateFolderDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="create-folder-dialog" /> : null,
}));
vi.mock("@/components/preview/FilePreviewModal", () => ({
  FilePreviewModal: () => <div data-testid="preview-modal" />,
}));
vi.mock("@/components/TopLoadingBar", () => ({
  TopLoadingBar: () => null,
}));

import { nodesApi } from "@/api/nodes";
import { toast } from "sonner";
import { FilesPage } from "@/pages/Files";

const move = vi.mocked(nodesApi.move);

function makeItem(id: string, name: string, type: "file" | "folder" = "file"): NodeListItem {
  return {
    id,
    owner_id: "owner",
    parent_id: "root",
    name,
    node_type: type,
  } as NodeListItem;
}

function makeData(items: NodeListItem[]) {
  return {
    items,
    total: items.length,
    folder: { node_id: "folder-1", node: { name: "My Folder" } },
    breadcrumbs: [],
  };
}

// Node's experimental global localStorage is unavailable without a backing file,
// and it shadows jsdom's. Install a simple in-memory stub for deterministic tests.
const memoryStorage = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => {
      store[k] = String(v);
    },
    removeItem: (k: string) => {
      delete store[k];
    },
    clear: () => {
      store = {};
    },
    key: (i: number) => Object.keys(store)[i] ?? null,
    get length() {
      return Object.keys(store).length;
    },
  };
})();
Object.defineProperty(window, "localStorage", { value: memoryStorage, configurable: true });
Object.defineProperty(globalThis, "localStorage", { value: memoryStorage, configurable: true });

function renderFiles(entries = ["/files/folders/folder-1"]) {
  return renderWithProviders(
    <Routes>
      <Route path="/files/folders/:nodeId" element={<FilesPage />} />
    </Routes>,
    { routerEntries: entries },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  fileBrowser.data = undefined;
  fileBrowser.isLoading = false;
  fileBrowser.error = null;
  infoPanel.selectedItem = null;
  memoryStorage.clear();
});

describe("FilesPage", () => {
  it("shows loading state via grid", () => {
    fileBrowser.isLoading = true;
    renderFiles();
    expect(screen.getByTestId("grid-loading")).toBeInTheDocument();
  });

  it("shows empty state when no items", () => {
    fileBrowser.data = makeData([]);
    renderFiles();
    expect(screen.getByTestId("grid-empty")).toBeInTheDocument();
  });

  it("renders error state", () => {
    fileBrowser.error = new Error("boom");
    renderFiles();
    expect(screen.getByText("Не удалось загрузить файлы.")).toBeInTheDocument();
  });

  it("renders items and folder name", () => {
    fileBrowser.data = makeData([makeItem("1", "a.txt"), makeItem("2", "b.txt")]);
    renderFiles();
    expect(screen.getByText("select-a.txt")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "My Folder" })).toBeInTheDocument();
  });

  it("selects a single item showing the action bar", async () => {
    fileBrowser.data = makeData([makeItem("1", "a.txt")]);
    const user = userEvent.setup();
    renderFiles();
    await user.click(screen.getByText("select-a.txt"));
    expect(await screen.findByTestId("action-bar")).toHaveTextContent("action:a.txt");
  });

  it("multi-selects with ctrl showing the multi-action bar", async () => {
    fileBrowser.data = makeData([makeItem("1", "a.txt"), makeItem("2", "b.txt")]);
    const user = userEvent.setup();
    renderFiles();
    await user.click(screen.getByText("ctrl-a.txt"));
    await user.click(screen.getByText("ctrl-b.txt"));
    expect(await screen.findByTestId("multi-action-bar")).toHaveTextContent("multi:2");
  });

  it("toggles to list view and persists", async () => {
    fileBrowser.data = makeData([makeItem("1", "a.txt")]);
    const user = userEvent.setup();
    renderFiles();
    await user.click(screen.getByLabelText("Список"));
    expect(memoryStorage.getItem("file-view-mode")).toBe("list");
  });

  it("opens create-folder dialog", async () => {
    fileBrowser.data = makeData([makeItem("1", "a.txt")]);
    const user = userEvent.setup();
    renderFiles();
    await user.click(screen.getByRole("button", { name: "Новая папка" }));
    expect(await screen.findByTestId("create-folder-dialog")).toBeInTheDocument();
  });

  it("sets breadcrumbs from folder data", async () => {
    fileBrowser.data = makeData([makeItem("1", "a.txt")]);
    renderFiles();
    await waitFor(() => expect(setCrumbs).toHaveBeenCalled());
    const last = setCrumbs.mock.calls.at(-1)![0];
    expect(last.at(-1)).toEqual({ label: "My Folder" });
  });

  describe("handleDrop", () => {
    it("moves a single item successfully", async () => {
      fileBrowser.data = makeData([makeItem("1", "a.txt"), makeItem("2", "folder", "folder")]);
      move.mockResolvedValue({} as never);
      const user = userEvent.setup();
      renderFiles();
      await user.click(screen.getByText("drop-a.txt"));

      await waitFor(() =>
        expect(move).toHaveBeenCalledWith("1", { target_parent_id: "target-folder" }),
      );
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Перемещено"));
    });

    it("reports a fully failed move", async () => {
      fileBrowser.data = makeData([makeItem("1", "a.txt")]);
      move.mockRejectedValue(new Error("nope"));
      const user = userEvent.setup();
      renderFiles();
      await user.click(screen.getByText("drop-a.txt"));

      await waitFor(() => expect(toast.error).toHaveBeenCalledWith("friendly error"));
    });

    it("reports a partial failure when moving the selection", async () => {
      fileBrowser.data = makeData([
        makeItem("1", "a.txt"),
        makeItem("2", "b.txt"),
        makeItem("3", "c.txt"),
      ]);
      const user = userEvent.setup();
      renderFiles();
      // Select all three via ctrl so the dragged item is part of the selection.
      await user.click(screen.getByText("ctrl-a.txt"));
      await user.click(screen.getByText("ctrl-b.txt"));
      await user.click(screen.getByText("ctrl-c.txt"));

      move.mockResolvedValueOnce({} as never).mockRejectedValueOnce(new Error("x"));
      // dragged id "1" is in selection -> moves selected (excluding target).
      await user.click(screen.getByText("drop-a.txt"));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          expect.stringContaining("Не удалось переместить"),
        ),
      );
    });
  });
});
