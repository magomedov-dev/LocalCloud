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
    batch.mockResolvedValue({
      a: { status: "ready", url: "https://x/a.png" },
      b: { status: "none", url: null },
    } as never);

    const { result } = renderHook(() => useThumbnails([imageNode("a"), imageNode("b")]), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.size).toBe(2));
    expect(batch).toHaveBeenCalledWith(["a", "b"], expect.anything());
    expect(result.current.get("a")).toBe("https://x/a.png");
    expect(result.current.get("b")).toBeNull();
    // Кэшируются оба терминальных исхода: ready (URL) и none (null) — узлы
    // со статусом none больше не попадают в батчи.
    expect(setCache).toHaveBeenCalledWith("a", "https://x/a.png");
    expect(setCache).toHaveBeenCalledWith("b", null);
  });

  it("does not cache pending results so they are re-polled", async () => {
    batch.mockResolvedValue({
      vid: { status: "pending", url: null },
    } as never);

    const { result } = renderHook(() => useThumbnails([imageNode("vid")]), {
      wrapper: wrapper(),
    });

    // pending отображается как иконка (null), но не кэшируется — узел
    // останется в наборе для повторного опроса.
    await waitFor(() => expect(result.current.get("vid")).toBeNull());
    expect(setCache).not.toHaveBeenCalled();
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

  it("skips ids with cached terminal values (URL or none) from the fetch set", async () => {
    // "have" уже имеет готовый URL в кэше, "absent" известен как none (null) —
    // оба терминальны и не запрашиваются. Запрашивается только "fresh".
    getCache.mockImplementation((id: string) => {
      if (id === "have") return "https://x/have.png";
      if (id === "absent") return null;
      return undefined;
    });
    batch.mockResolvedValue({
      fresh: { status: "ready", url: "https://x/fresh.png" },
    } as never);

    const { result } = renderHook(
      () => useThumbnails([imageNode("have"), imageNode("absent"), imageNode("fresh")]),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.get("fresh")).toBe("https://x/fresh.png"));
    expect(batch).toHaveBeenCalledWith(["fresh"], expect.anything());
    expect(result.current.get("have")).toBe("https://x/have.png");
    expect(result.current.get("absent")).toBeNull();
  });

  it("filters out unsupported files and folders from the fetch set", async () => {
    batch.mockResolvedValue({
      img: { status: "ready", url: "https://x/img.png" },
    } as never);
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
    batch.mockResolvedValue({
      book: { status: "ready", url: "https://x/book.webp" },
    } as never);
    const { result } = renderHook(() => useThumbnails([pdfNode("book")]), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.get("book")).toBe("https://x/book.webp"));
    expect(batch).toHaveBeenCalledWith(["book"], expect.anything());
  });

  it("fetches only uncached ids when the item set grows (pagination)", async () => {
    batch.mockResolvedValueOnce({
      a: { status: "ready", url: "https://x/a.png" },
    } as never);
    const { result, rerender } = renderHook(
      ({ items }: { items: NodeListItem[] }) => useThumbnails(items),
      { wrapper: wrapper(), initialProps: { items: [imageNode("a")] } },
    );
    await waitFor(() => expect(result.current.get("a")).toBe("https://x/a.png"));

    // Подгрузилась следующая страница: "a" уже в кэше, запрашивается только "b".
    batch.mockResolvedValueOnce({
      b: { status: "ready", url: "https://x/b.png" },
    } as never);
    rerender({ items: [imageNode("a"), imageNode("b")] });

    await waitFor(() => expect(result.current.get("b")).toBe("https://x/b.png"));
    expect(batch).toHaveBeenCalledTimes(2);
    expect(batch).toHaveBeenLastCalledWith(["b"], expect.anything());
    expect(result.current.get("a")).toBe("https://x/a.png");
  });

  it("chunks more than 100 ids into separate batch requests of <=100", async () => {
    batch.mockImplementation((ids: string[]) =>
      Promise.resolve(
        Object.fromEntries(
          ids.map((id) => [id, { status: "ready", url: `https://x/${id}.png` }]),
        ),
      ),
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
