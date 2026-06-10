import type { ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeTestQueryClient } from "@/test/utils";

vi.mock("@/api/public-links", () => ({ publicLinksApi: { list: vi.fn() } }));

import { publicLinksApi } from "@/api/public-links";
import { useShareBadges } from "./useShareBadges";
import type { NodeListItem } from "@/types/nodes";

const list = vi.mocked(publicLinksApi.list);

function wrapper() {
  const qc = makeTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function node(id: string): NodeListItem {
  return { id, name: id, node_type: "file" } as NodeListItem;
}
function link(node_id: string) {
  return { id: `link-${node_id}`, node_id };
}

beforeEach(() => vi.clearAllMocks());

describe("useShareBadges", () => {
  it("returns empty map before data loads", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    const { result } = renderHook(() => useShareBadges([node("a")]), { wrapper: wrapper() });
    expect(result.current.size).toBe(0);
  });

  it("builds badges only for nodes present in the current list", async () => {
    list.mockResolvedValue({
      items: [link("a"), link("zzz-not-in-list")],
      meta: { total: 2 },
    } as never);

    const { result } = renderHook(() => useShareBadges([node("a"), node("b")]), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.size).toBe(1));
    expect(result.current.get("a")).toEqual({ hasPublicLink: true, hasSharedAccess: false });
    expect(result.current.has("b")).toBe(false);
    expect(result.current.has("zzz-not-in-list")).toBe(false);
  });

  it("paginates until total reached", async () => {
    const fullPage = Array.from({ length: 100 }, (_, i) => link(`p1-${i}`));
    list
      .mockResolvedValueOnce({ items: fullPage, meta: { total: 101 } } as never)
      .mockResolvedValueOnce({ items: [link("target")], meta: { total: 101 } } as never);

    const { result } = renderHook(() => useShareBadges([node("target")]), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.has("target")).toBe(true));
    expect(list).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenNthCalledWith(1, { is_active: true, limit: 100, offset: 0 });
    expect(list).toHaveBeenNthCalledWith(2, { is_active: true, limit: 100, offset: 100 });
  });

  it("stops paginating on a short page", async () => {
    list.mockResolvedValue({ items: [link("a")], meta: { total: 999 } } as never);
    const { result } = renderHook(() => useShareBadges([node("a")]), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.has("a")).toBe(true));
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("returns empty map for empty item list even with active links", async () => {
    list.mockResolvedValue({ items: [link("a")], meta: { total: 1 } } as never);
    const { result } = renderHook(() => useShareBadges([]), { wrapper: wrapper() });
    await waitFor(() => expect(list).toHaveBeenCalled());
    expect(result.current.size).toBe(0);
  });
});
