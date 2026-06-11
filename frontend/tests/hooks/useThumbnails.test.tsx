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
  // Тип без поддержки превью — миниатюра не запрашивается.
  return {
    id,
    name: id,
    node_type: "file",
    file_mime_type: "application/octet-stream",
  } as NodeListItem;
}
function pdfNode(id: string): NodeListItem {
  return { id, name: id, node_type: "file", file_mime_type: "application/pdf" } as NodeListItem;
}
function folderNode(id: string): NodeListItem {
  return { id, name: id, node_type: "folder" } as NodeListItem;
}

beforeEach(() => {
  vi.clearAllMocks();
  // Имитируем sessionStorage как in-memory store, чтобы set/get делали round-trip:
  // отрицательные результаты теперь живут только здесь, не в React Query.
  const store = new Map<string, string | null>();
  getCache.mockImplementation((id: string) => (store.has(id) ? store.get(id) : undefined));
  setCache.mockImplementation((id: string, value: string | null) => {
    store.set(id, value);
  });
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
    // Кэшируем только положительный результат; null не кэшируем, чтобы можно
    // было опросить превью повторно, когда оно сгенерируется.
    expect(setCache).toHaveBeenCalledWith("a", "https://x/a.png");
    expect(setCache).not.toHaveBeenCalledWith("b", null);
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

  it("skips ids with a cached URL but re-requests pending (null) ids", async () => {
    // "have" уже имеет готовый URL в кэше → не запрашивается повторно.
    // "pending" известен как null → перезапрашивается (превью могло появиться).
    getCache.mockImplementation((id: string) =>
      id === "have" ? "https://x/have.png" : undefined,
    );
    batch.mockResolvedValue({ pending: "https://x/pending.png" } as never);

    const { result } = renderHook(
      () => useThumbnails([imageNode("have"), imageNode("pending")]),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.get("pending")).toBe("https://x/pending.png"));
    // Запрашивается только "pending"; "have" обслужен из кэша.
    expect(batch).toHaveBeenCalledWith(["pending"], expect.anything());
    expect(result.current.get("have")).toBe("https://x/have.png");
  });

  it("filters out unsupported files and folders from the fetch set", async () => {
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

  it("fetches thumbnails for preview-supported non-image files (PDF)", async () => {
    batch.mockResolvedValue({ book: "https://x/book.webp" } as never);
    const { result } = renderHook(() => useThumbnails([pdfNode("book")]), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.get("book")).toBe("https://x/book.webp"));
    expect(batch).toHaveBeenCalledWith(["book"], expect.anything());
  });

  it("chunks more than 100 ids into separate batch requests of <=100", async () => {
    batch.mockImplementation((ids: string[]) =>
      Promise.resolve(Object.fromEntries(ids.map((id) => [id, `https://x/${id}.png`]))),
    );
    const items = Array.from({ length: 150 }, (_, i) => imageNode(`n${i}`));

    const { result } = renderHook(() => useThumbnails(items), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.size).toBe(150));
    // Серверный лимит 100 → 150 элементов = 2 запроса (100 + 50).
    expect(batch).toHaveBeenCalledTimes(2);
    for (const call of batch.mock.calls) {
      expect((call[0] as string[]).length).toBeLessThanOrEqual(100);
    }
    expect(result.current.get("n0")).toBe("https://x/n0.png");
    expect(result.current.get("n149")).toBe("https://x/n149.png");
  });
});
