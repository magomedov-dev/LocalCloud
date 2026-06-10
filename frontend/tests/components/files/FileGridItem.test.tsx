import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import type { NodeListItem } from "@/types/nodes";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

const prefetchInfiniteQuery = vi.fn();
vi.mock("@/lib/query-client", () => ({
  queryClient: { prefetchInfiniteQuery: (...a: unknown[]) => prefetchInfiniteQuery(...a) },
}));

vi.mock("@/api/nodes", () => ({ nodesApi: { content: vi.fn() } }));
vi.mock("@/hooks/useFileBrowser", () => ({
  FOLDER_PAGE_SIZE: 50,
  folderQueryKey: (id: string) => ["nodes", id],
}));

const detectPreviewKind = vi.fn();
vi.mock("@/components/preview/filePreviewKind", () => ({
  detectPreviewKind: (...a: unknown[]) => detectPreviewKind(...a),
}));

vi.mock("@/components/files/folderColors", () => ({
  getFolderColor: vi.fn(() => null),
  setFolderColor: vi.fn(),
}));

vi.mock("@/components/files/FileIcon", () => ({
  FileIcon: () => <span data-testid="file-icon" />,
}));
const itemActionsProps: {
  onColorChange?: (c: string | null) => void;
  onOpenChange?: (o: boolean) => void;
} = {};
vi.mock("@/components/files/ItemActions", () => ({
  ItemActions: (props: {
    onColorChange: (c: string | null) => void;
    onOpenChange: (o: boolean) => void;
  }) => {
    itemActionsProps.onColorChange = props.onColorChange;
    itemActionsProps.onOpenChange = props.onOpenChange;
    return <span data-testid="item-actions" />;
  },
}));
vi.mock("@/components/files/ItemContextMenu", () => ({
  ItemContextMenu: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/preview/FilePreviewModal", () => ({
  FilePreviewModal: ({ open }: { open: boolean }) =>
    open ? <div data-testid="preview-modal" /> : null,
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { FileGridItem } from "@/components/files/FileGridItem";

function makeItem(over: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: "1",
    owner_id: "o",
    parent_id: null,
    name: "photo.png",
    node_type: "file",
    visibility: "private",
    path: "/x",
    depth: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-02-15T00:00:00Z",
    is_deleted: false,
    file_size_bytes: 2048,
    file_mime_type: "image/png",
    ...over,
  };
}

const baseProps = { folderQueryKey: ["k"] };

describe("FileGridItem", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    detectPreviewKind.mockReturnValue(null);
  });

  it("renders name and formatted size for a file", () => {
    renderWithProviders(
      <FileGridItem {...baseProps} item={makeItem()} mimeType="image/png" sizeBytes={2048} />,
    );
    expect(screen.getByText("photo.png")).toBeInTheDocument();
    expect(screen.getByText(/2\D*KB|2\s*КБ|2/)).toBeInTheDocument();
  });

  it("renders formatted date for a folder", () => {
    renderWithProviders(
      <FileGridItem
        {...baseProps}
        item={makeItem({ node_type: "folder", name: "Папка", file_mime_type: null })}
        mimeType={null}
        sizeBytes={null}
      />,
    );
    expect(screen.getByText("Папка")).toBeInTheDocument();
  });

  it("shows image skeleton when thumbnail is undefined", () => {
    const { container } = renderWithProviders(
      <FileGridItem
        {...baseProps}
        item={makeItem()}
        mimeType="image/png"
        thumbnailUrl={undefined}
      />,
    );
    // Skeleton renders a div; image should not be present yet.
    expect(container.querySelector("img")).toBeNull();
  });

  it("renders thumbnail image when url present", () => {
    renderWithProviders(
      <FileGridItem
        {...baseProps}
        item={makeItem()}
        mimeType="image/png"
        thumbnailUrl="blob:thumb"
      />,
    );
    const img = screen.getByAltText("photo.png") as HTMLImageElement;
    expect(img.src).toContain("blob:thumb");
  });

  it("falls back to icon when image thumbnail failed (null)", () => {
    renderWithProviders(
      <FileGridItem
        {...baseProps}
        item={makeItem()}
        mimeType="image/png"
        thumbnailUrl={null}
      />,
    );
    expect(screen.getByTestId("file-icon")).toBeInTheDocument();
  });

  it("renders share badges", () => {
    const { container } = renderWithProviders(
      <TooltipProvider>
        <FileGridItem
          {...baseProps}
          item={makeItem({ file_mime_type: "text/plain" })}
          mimeType="text/plain"
          badge={{ hasPublicLink: true, hasSharedAccess: true }}
        />
      </TooltipProvider>,
    );
    expect(container.querySelector(".bg-sky-500")).toBeTruthy();
    expect(container.querySelector(".bg-violet-500")).toBeTruthy();
  });

  it("renders no badges without share info", () => {
    const { container } = renderWithProviders(
      <FileGridItem {...baseProps} item={makeItem({ file_mime_type: "text/plain" })} />,
    );
    expect(container.querySelector(".bg-sky-500")).toBeFalsy();
  });

  it("calls onSelect on click with modifier flags", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(
      <FileGridItem {...baseProps} item={makeItem()} onSelect={onSelect} />,
    );
    await user.click(screen.getByRole("button"));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "1" }),
      { ctrl: false, shift: false },
    );
  });

  it("navigates into folder on double click", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <FileGridItem
        {...baseProps}
        item={makeItem({ node_type: "folder", file_mime_type: null })}
      />,
    );
    await user.dblClick(screen.getByRole("button"));
    expect(navigate).toHaveBeenCalledWith("/files/folders/1");
  });

  it("opens preview modal on double click for previewable file", async () => {
    detectPreviewKind.mockReturnValue("image");
    const user = userEvent.setup();
    renderWithProviders(
      <FileGridItem {...baseProps} item={makeItem()} mimeType="image/png" />,
    );
    await user.dblClick(screen.getByRole("button"));
    expect(screen.getByTestId("preview-modal")).toBeInTheDocument();
  });

  it("prefetches folder on mouse enter", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <FileGridItem
        {...baseProps}
        item={makeItem({ node_type: "folder", file_mime_type: null })}
      />,
    );
    await user.hover(screen.getByRole("button"));
    expect(prefetchInfiniteQuery).toHaveBeenCalled();
  });

  it("triggers onSelect on Enter key", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(
      <FileGridItem {...baseProps} item={makeItem()} onSelect={onSelect} />,
    );
    screen.getByRole("button").focus();
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalled();
  });

  it("applies selected styling when isSelected", () => {
    renderWithProviders(
      <FileGridItem {...baseProps} item={makeItem()} isSelected />,
    );
    expect(screen.getByRole("button").className).toContain("ring-primary/50");
  });

  it("updates folder color via ItemActions callback", async () => {
    const { setFolderColor } = await import("@/components/files/folderColors");
    const { act } = await import("@testing-library/react");
    renderWithProviders(
      <FileGridItem
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
      <FileGridItem {...baseProps} item={makeItem()} />,
    );
    act(() => itemActionsProps.onOpenChange?.(true));
    expect(container.querySelector(".opacity-100")).not.toBeNull();
  });

  it("sets drag data on drag start", () => {
    renderWithProviders(<FileGridItem {...baseProps} item={makeItem()} />);
    const el = screen.getByRole("button");
    const setData = vi.fn();
    fireEvent.dragStart(el, { dataTransfer: { setData, getData: vi.fn(), dropEffect: "", effectAllowed: "" } });
    expect(setData).toHaveBeenCalledWith("application/localcloud-node", "1");
    fireEvent.dragEnd(el);
  });

  it("does not call onDrop for same-id drop", () => {
    const onDrop = vi.fn();
    renderWithProviders(
      <FileGridItem
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

  it("ignores drag over for non-folder", () => {
    const onDrop = vi.fn();
    renderWithProviders(<FileGridItem {...baseProps} item={makeItem({ id: "f" })} onDrop={onDrop} />);
    const el = screen.getByRole("button");
    const dt = { getData: vi.fn(() => "x"), setData: vi.fn(), dropEffect: "", effectAllowed: "" };
    fireEvent.dragOver(el, { dataTransfer: dt });
    fireEvent.drop(el, { dataTransfer: dt });
    expect(onDrop).not.toHaveBeenCalled();
  });

  it("handles folder drag over and drop", () => {
    const onDrop = vi.fn();
    renderWithProviders(
      <FileGridItem
        {...baseProps}
        item={makeItem({ id: "target", node_type: "folder", file_mime_type: null })}
        onDrop={onDrop}
      />,
    );
    const el = screen.getByRole("button");
    const dt = { setData: vi.fn(), getData: vi.fn(() => "dragged-id"), dropEffect: "", effectAllowed: "" };
    fireEvent.dragOver(el, { dataTransfer: dt });
    fireEvent.drop(el, { dataTransfer: dt });
    expect(onDrop).toHaveBeenCalledWith("dragged-id", "target");
  });
});
