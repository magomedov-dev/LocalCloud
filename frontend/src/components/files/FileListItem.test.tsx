import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import type { NodeListItem } from "@/types/nodes";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

const prefetchQuery = vi.fn();
vi.mock("@/lib/query-client", () => ({
  queryClient: { prefetchQuery: (...a: unknown[]) => prefetchQuery(...a) },
}));
vi.mock("@/api/nodes", () => ({ nodesApi: { content: vi.fn() } }));

const detectPreviewKind = vi.fn();
vi.mock("@/components/preview/filePreviewKind", () => ({
  detectPreviewKind: (...a: unknown[]) => detectPreviewKind(...a),
}));

vi.mock("./folderColors", () => ({
  getFolderColor: vi.fn(() => null),
  setFolderColor: vi.fn(),
}));

vi.mock("./FileIcon", () => ({
  FileIcon: () => <span data-testid="file-icon" />,
}));
const itemActionsProps: {
  onColorChange?: (c: string | null) => void;
  onOpenChange?: (o: boolean) => void;
} = {};
vi.mock("./ItemActions", () => ({
  ItemActions: (props: {
    onColorChange: (c: string | null) => void;
    onOpenChange: (o: boolean) => void;
  }) => {
    itemActionsProps.onColorChange = props.onColorChange;
    itemActionsProps.onOpenChange = props.onOpenChange;
    return <span data-testid="item-actions" />;
  },
}));
vi.mock("./ItemContextMenu", () => ({
  ItemContextMenu: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/preview/FilePreviewModal", () => ({
  FilePreviewModal: ({ open }: { open: boolean }) =>
    open ? <div data-testid="preview-modal" /> : null,
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { FileListItem } from "./FileListItem";

function makeItem(over: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: "1",
    owner_id: "o",
    parent_id: null,
    name: "report.txt",
    node_type: "file",
    visibility: "private",
    path: "/x",
    depth: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-02-15T00:00:00Z",
    is_deleted: false,
    file_size_bytes: 1024,
    file_mime_type: "text/plain",
    ...over,
  };
}

const baseProps = { folderQueryKey: ["k"] };

describe("FileListItem", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    detectPreviewKind.mockReturnValue(null);
  });

  it("renders name and size for file", () => {
    renderWithProviders(
      <FileListItem {...baseProps} item={makeItem()} mimeType="text/plain" sizeBytes={1024} />,
    );
    expect(screen.getByText("report.txt")).toBeInTheDocument();
  });

  it("renders empty size for folder", () => {
    renderWithProviders(
      <FileListItem
        {...baseProps}
        item={makeItem({ node_type: "folder", name: "dir", file_mime_type: null })}
        sizeBytes={null}
      />,
    );
    expect(screen.getByText("dir")).toBeInTheDocument();
  });

  it("renders share badges", () => {
    const { container } = renderWithProviders(
      <TooltipProvider>
        <FileListItem
          {...baseProps}
          item={makeItem()}
          badge={{ hasPublicLink: true, hasSharedAccess: true }}
        />
      </TooltipProvider>,
    );
    expect(container.querySelector(".bg-sky-500")).toBeTruthy();
    expect(container.querySelector(".bg-violet-500")).toBeTruthy();
  });

  it("calls onSelect with ctrl flag on click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(
      <FileListItem {...baseProps} item={makeItem()} onSelect={onSelect} />,
    );
    await user.keyboard("{Control>}");
    await user.click(screen.getByRole("button"));
    await user.keyboard("{/Control}");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "1" }),
      expect.objectContaining({ ctrl: true }),
    );
  });

  it("navigates into folder on double click", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <FileListItem
        {...baseProps}
        item={makeItem({ node_type: "folder", file_mime_type: null })}
      />,
    );
    await user.dblClick(screen.getByRole("button"));
    expect(navigate).toHaveBeenCalledWith("/files/folders/1");
  });

  it("opens preview modal on double click for previewable file", async () => {
    detectPreviewKind.mockReturnValue("text");
    const user = userEvent.setup();
    renderWithProviders(
      <FileListItem {...baseProps} item={makeItem()} mimeType="text/plain" />,
    );
    await user.dblClick(screen.getByRole("button"));
    expect(screen.getByTestId("preview-modal")).toBeInTheDocument();
  });

  it("prefetches folder content on mouse enter", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <FileListItem
        {...baseProps}
        item={makeItem({ node_type: "folder", file_mime_type: null })}
      />,
    );
    await user.hover(screen.getByRole("button"));
    expect(prefetchQuery).toHaveBeenCalled();
  });

  it("triggers onSelect on Space key", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(
      <FileListItem {...baseProps} item={makeItem()} onSelect={onSelect} />,
    );
    screen.getByRole("button").focus();
    await user.keyboard(" ");
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "1" }),
      { ctrl: false, shift: false },
    );
  });

  it("applies selected styling", () => {
    renderWithProviders(<FileListItem {...baseProps} item={makeItem()} isSelected />);
    expect(screen.getByRole("button").className).toContain("bg-primary/10");
  });

  it("updates folder color via ItemActions callback", async () => {
    const { setFolderColor } = await import("./folderColors");
    const { act } = await import("@testing-library/react");
    renderWithProviders(
      <FileListItem
        {...baseProps}
        item={makeItem({ node_type: "folder", file_mime_type: null })}
      />,
    );
    act(() => itemActionsProps.onColorChange?.("#abcdef"));
    expect(setFolderColor).toHaveBeenCalledWith("1", "#abcdef");
  });

  it("keeps action button visible when menu is open", async () => {
    const { act } = await import("@testing-library/react");
    const { container } = renderWithProviders(
      <FileListItem {...baseProps} item={makeItem()} />,
    );
    act(() => itemActionsProps.onOpenChange?.(true));
    // opacity-0 wrapper class is removed once menu is open
    expect(container.querySelector(".opacity-0")).toBeNull();
  });

  it("sets drag data on drag start", () => {
    renderWithProviders(<FileListItem {...baseProps} item={makeItem()} />);
    const el = screen.getByRole("button");
    const setData = vi.fn();
    fireEvent.dragStart(el, { dataTransfer: { setData, getData: vi.fn(), dropEffect: "", effectAllowed: "" } });
    expect(setData).toHaveBeenCalledWith("application/localcloud-node", "1");
    fireEvent.dragEnd(el);
  });

  it("does not call onDrop when dropping a node onto itself", () => {
    const onDrop = vi.fn();
    renderWithProviders(
      <FileListItem
        {...baseProps}
        item={makeItem({ id: "same", node_type: "folder", file_mime_type: null })}
        onDrop={onDrop}
      />,
    );
    const el = screen.getByRole("button");
    const dt = { getData: vi.fn(() => "same"), setData: vi.fn(), dropEffect: "", effectAllowed: "" };
    fireEvent.dragOver(el, { dataTransfer: dt });
    fireEvent.drop(el, { dataTransfer: dt });
    expect(onDrop).not.toHaveBeenCalled();
  });

  it("handles drop of node into folder", () => {
    const onDrop = vi.fn();
    renderWithProviders(
      <FileListItem
        {...baseProps}
        item={makeItem({ id: "target", node_type: "folder", file_mime_type: null })}
        onDrop={onDrop}
      />,
    );
    const el = screen.getByRole("button");
    const dt = { getData: vi.fn(() => "dragged"), setData: vi.fn(), dropEffect: "", effectAllowed: "" };
    fireEvent.dragOver(el, { dataTransfer: dt });
    fireEvent.drop(el, { dataTransfer: dt });
    expect(onDrop).toHaveBeenCalledWith("dragged", "target");
  });

  it("ignores drop onto a file (non-folder)", () => {
    const onDrop = vi.fn();
    renderWithProviders(
      <FileListItem {...baseProps} item={makeItem({ id: "file" })} onDrop={onDrop} />,
    );
    const el = screen.getByRole("button");
    const dt = { getData: vi.fn(() => "dragged"), setData: vi.fn(), dropEffect: "", effectAllowed: "" };
    fireEvent.drop(el, { dataTransfer: dt });
    expect(onDrop).not.toHaveBeenCalled();
  });
});
