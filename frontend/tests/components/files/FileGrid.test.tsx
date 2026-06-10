import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import type { NodeListItem } from "@/types/nodes";

class IntersectionObserverStub {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => []);
  root = null;
  rootMargin = "";
  thresholds = [];
}
globalThis.IntersectionObserver =
  globalThis.IntersectionObserver || (IntersectionObserverStub as never);

vi.mock("@/hooks/useThumbnails", () => ({
  useThumbnails: () => new Map(),
}));
vi.mock("@/hooks/useShareBadges", () => ({
  useShareBadges: () => new Map(),
}));

vi.mock("@/components/files/FileGridItem", () => ({
  FileGridItem: ({ item }: { item: NodeListItem }) => (
    <div data-testid="grid-item">{item.name}</div>
  ),
}));
vi.mock("@/components/files/FileListItem", () => ({
  FileListItem: ({ item }: { item: NodeListItem }) => (
    <div data-testid="list-item">{item.name}</div>
  ),
}));

import { FileGrid } from "@/components/files/FileGrid";

function makeItem(over: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: over.id ?? "1",
    owner_id: "o",
    parent_id: null,
    name: over.name ?? "file",
    node_type: over.node_type ?? "file",
    visibility: "private",
    path: "/x",
    depth: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    is_deleted: false,
    file_size_bytes: 10,
    file_mime_type: "text/plain",
    ...over,
  };
}

const baseProps = {
  folderQueryKey: ["k"],
  isLoading: false,
};

describe("FileGrid", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders loading skeletons (grid)", () => {
    const { container } = renderWithProviders(
      <FileGrid {...baseProps} items={[]} isLoading view="grid" />,
    );
    expect(container.querySelectorAll(".grid").length).toBeGreaterThan(0);
    expect(screen.queryByText("Папка пуста")).not.toBeInTheDocument();
  });

  it("renders loading skeletons (list)", () => {
    renderWithProviders(<FileGrid {...baseProps} items={[]} isLoading view="list" />);
    expect(screen.queryByText("Папка пуста")).not.toBeInTheDocument();
  });

  it("renders empty state when no items", () => {
    renderWithProviders(<FileGrid {...baseProps} items={[]} view="grid" />);
    expect(screen.getByText("Папка пуста")).toBeInTheDocument();
  });

  it("renders grid items in grid view", () => {
    renderWithProviders(
      <FileGrid
        {...baseProps}
        items={[makeItem({ id: "1", name: "alpha" }), makeItem({ id: "2", name: "beta" })]}
        view="grid"
      />,
    );
    expect(screen.getAllByTestId("grid-item")).toHaveLength(2);
  });

  it("renders list items and header in list view", () => {
    renderWithProviders(
      <FileGrid {...baseProps} items={[makeItem({ name: "alpha" })]} view="list" />,
    );
    expect(screen.getByTestId("list-item")).toBeInTheDocument();
    expect(screen.getByText("Название")).toBeInTheDocument();
    expect(screen.getByText("Размер")).toBeInTheDocument();
  });

  it("sorts folders before files", () => {
    renderWithProviders(
      <FileGrid
        {...baseProps}
        items={[
          makeItem({ id: "1", name: "zfile", node_type: "file" }),
          makeItem({ id: "2", name: "afolder", node_type: "folder" }),
        ]}
        view="grid"
      />,
    );
    const items = screen.getAllByTestId("grid-item");
    expect(items[0]).toHaveTextContent("afolder");
  });

  it("calls onDeselect on container click", async () => {
    const user = userEvent.setup();
    const onDeselect = vi.fn();
    renderWithProviders(
      <FileGrid
        {...baseProps}
        items={[makeItem()]}
        view="grid"
        onDeselect={onDeselect}
      />,
    );
    await user.click(screen.getByTestId("grid-item"));
    expect(onDeselect).toHaveBeenCalled();
  });

  it("renders load-more button when hasNextPage", () => {
    renderWithProviders(
      <FileGrid
        {...baseProps}
        items={[makeItem()]}
        view="grid"
        hasNextPage
        onLoadMore={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Показать ещё" })).toBeInTheDocument();
  });

  it("calls onLoadMore when button clicked", async () => {
    const user = userEvent.setup();
    const onLoadMore = vi.fn();
    renderWithProviders(
      <FileGrid
        {...baseProps}
        items={[makeItem()]}
        view="list"
        hasNextPage
        onLoadMore={onLoadMore}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Показать ещё" }));
    expect(onLoadMore).toHaveBeenCalled();
  });

  it("shows spinner instead of button when fetching next page", () => {
    renderWithProviders(
      <FileGrid
        {...baseProps}
        items={[makeItem()]}
        view="grid"
        hasNextPage
        isFetchingNextPage
        onLoadMore={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
  });

  it("renders no footer when no next page", () => {
    renderWithProviders(<FileGrid {...baseProps} items={[makeItem()]} view="grid" />);
    expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
  });
});
