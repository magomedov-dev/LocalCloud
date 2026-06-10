import type { ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeTestQueryClient } from "@tests/utils";

vi.mock("@/api/nodes", () => ({ nodesApi: { list: vi.fn(), content: vi.fn() } }));

import { nodesApi } from "@/api/nodes";
import { useFileBrowser, folderQueryKey, FOLDER_PAGE_SIZE } from "@/hooks/useFileBrowser";

const list = vi.mocked(nodesApi.list);
const content = vi.mocked(nodesApi.content);

function wrapper() {
  const qc = makeTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function makeItems(n: number, prefix = "i") {
  return Array.from({ length: n }, (_, k) => ({ id: `${prefix}${k}`, name: `${prefix}${k}` }));
}

beforeEach(() => vi.clearAllMocks());

describe("folderQueryKey", () => {
  it("returns root key without nodeId", () => {
    expect(folderQueryKey()).toEqual(["nodes", "root"]);
  });
  it("returns content key with nodeId", () => {
    expect(folderQueryKey("n1")).toEqual(["nodes", "n1", "content"]);
  });
});

describe("useFileBrowser", () => {
  it("loads root listing when no nodeId given", async () => {
    list.mockResolvedValue({ items: makeItems(2), meta: { total: 2 } } as never);

    const { result } = renderHook(() => useFileBrowser(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(list).toHaveBeenCalledWith({ limit: FOLDER_PAGE_SIZE, offset: 0 });
    expect(result.current.data?.items).toHaveLength(2);
    expect(result.current.data?.total).toBe(2);
    expect(result.current.data?.folder).toBeNull();
    expect(result.current.data?.breadcrumbs).toEqual([]);
    expect(result.current.hasNextPage).toBe(false);
  });

  it("loads folder content with breadcrumbs and folder when nodeId given", async () => {
    content.mockResolvedValue({
      items: makeItems(1),
      total: 1,
      folder: { id: "f", node_id: "n1" },
      breadcrumbs: [{ id: "b", name: "root" }],
    } as never);

    const { result } = renderHook(() => useFileBrowser("n1"), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(content).toHaveBeenCalledWith("n1", { limit: FOLDER_PAGE_SIZE, offset: 0 });
    expect(result.current.data?.folder).toEqual({ id: "f", node_id: "n1" });
    expect(result.current.data?.breadcrumbs).toHaveLength(1);
  });

  it("paginates: hasNextPage when first full page, fetchNextPage merges items", async () => {
    list
      .mockResolvedValueOnce({
        items: makeItems(FOLDER_PAGE_SIZE, "a"),
        meta: { total: FOLDER_PAGE_SIZE + 1 },
      } as never)
      .mockResolvedValueOnce({
        items: makeItems(1, "b"),
        meta: { total: FOLDER_PAGE_SIZE + 1 },
      } as never);

    const { result } = renderHook(() => useFileBrowser(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.data?.items).toHaveLength(FOLDER_PAGE_SIZE));
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    await waitFor(() => expect(result.current.data?.items).toHaveLength(FOLDER_PAGE_SIZE + 1));
    expect(list).toHaveBeenLastCalledWith({ limit: FOLDER_PAGE_SIZE, offset: FOLDER_PAGE_SIZE });
    expect(result.current.hasNextPage).toBe(false);
  });

  it("surfaces query error", async () => {
    list.mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useFileBrowser(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect((result.current.error as Error).message).toBe("network down");
    expect(result.current.data).toBeUndefined();
  });
});
