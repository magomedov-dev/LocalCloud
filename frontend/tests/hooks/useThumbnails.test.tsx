import type { ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/api/nodes", () => ({ nodesApi: { thumbnailsBatch: vi.fn() } }));
vi.mock("@/lib/thumbnailCache", () => ({
  getThumbnailCache: vi.fn(),
  setThumbnailCache: vi.fn(),
}));

import { nodesApi } from "@/api/nodes";
import { getThumbnailCache, setThumbnailCache } from "@/lib/thumbnailCache";
import { useThumbnails } from "@/hooks/useThumbnails";
import type { NodeListItem } from "@/types/nodes";

const batch = vi.mocked(nodesApi.thumbnailsBatch);
const getCache = vi.mocked(getThumbnailCache);
const setCache = vi.mocked(setThumbnailCache);

function wrapper() {
  // gcTime > 0: записанные через setQueryData значения ["thumbnail", id] не
  // должны мгновенно вычищаться, иначе map не сможет их прочитать на re-render.
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function imageNode(id: string): NodeListItem {
  return { id, name: id, node_type: "file", file_mime_type: "image/png" } as NodeListItem;
}
function fileNode(id: string): NodeListItem {
  return { id, name: id, node_type: "file", file_mime_type: "text/plain" } as NodeListItem;
}
function folderNode(id: string): NodeListItem {
  return { id, name: id, node_type: "folder" } as NodeListItem;
}

beforeEach(() => {
  vi.clearAllMocks();
  getCache.mockReturnValue(undefined);
});

describe("useThumbnails", () => {
  it("does not fetch when there are no image items", async () => {
    const { result } = renderHook(() => useThumbnails([fileNode("t"), folderNode("f")]), {
      wrapper: wrapper(),
    });
    expect(result.current.size).toBe(0);
    expect(batch).not.toHaveBeenCalled();
  });

  it("batch-fetches uncached image ids and populates the map", async () => {
    batch.mockResolvedValue({ a: "https://x/a.png", b: null } as never);

    const { result } = renderHook(() => useThumbnails([imageNode("a"), imageNode("b")]), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.size).toBe(2));
    expect(batch).toHaveBeenCalledWith(["a", "b"], expect.anything());
    expect(result.current.get("a")).toBe("https://x/a.png");
    expect(result.current.get("b")).toBeNull();
    // Записывает в sessionStorage кэш.
    expect(setCache).toHaveBeenCalledWith("a", "https://x/a.png");
    expect(setCache).toHaveBeenCalledWith("b", null);
  });

  it("serves values from sessionStorage cache without fetching", async () => {
    getCache.mockImplementation((id: string) =>
      id === "cached" ? "https://x/cached.png" : undefined,
    );

    const { result } = renderHook(() => useThumbnails([imageNode("cached")]), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.get("cached")).toBe("https://x/cached.png"));
    expect(batch).not.toHaveBeenCalled();
  });

  it("only fetches ids missing from session cache", async () => {
    getCache.mockImplementation((id: string) => (id === "have" ? null : undefined));
    batch.mockResolvedValue({ need: "https://x/need.png" } as never);

    const { result } = renderHook(() => useThumbnails([imageNode("have"), imageNode("need")]), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.get("need")).toBe("https://x/need.png"));
    expect(batch).toHaveBeenCalledWith(["need"], expect.anything());
    // "have" известен как null из session cache.
    expect(result.current.get("have")).toBeNull();
  });

  it("filters out non-image files from the fetch set", async () => {
    batch.mockResolvedValue({ img: "https://x/img.png" } as never);
    const { result } = renderHook(
      () => useThumbnails([imageNode("img"), fileNode("doc"), folderNode("dir")]),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.get("img")).toBe("https://x/img.png"));
    expect(batch).toHaveBeenCalledWith(["img"], expect.anything());
    expect(result.current.has("doc")).toBe(false);
    expect(result.current.has("dir")).toBe(false);
  });
});
