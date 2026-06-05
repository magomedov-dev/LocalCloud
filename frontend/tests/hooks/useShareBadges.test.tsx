import type { ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeTestQueryClient } from "@tests/utils";

vi.mock("@/api/public-links", () => ({ publicLinksApi: { activeNodeIds: vi.fn() } }));
vi.mock("@/api/permissions", () => ({ permissionsApi: { sharedByMe: vi.fn() } }));

import { publicLinksApi } from "@/api/public-links";
import { permissionsApi } from "@/api/permissions";
import { useShareBadges } from "@/hooks/useShareBadges";
import type { NodeListItem } from "@/types/nodes";

const activeNodeIds = vi.mocked(publicLinksApi.activeNodeIds);
const sharedByMe = vi.mocked(permissionsApi.sharedByMe);

function wrapper() {
  const qc = makeTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function node(id: string): NodeListItem {
  return { id, name: id, node_type: "file" } as NodeListItem;
}

beforeEach(() => {
  vi.clearAllMocks();
  activeNodeIds.mockResolvedValue([]);
  sharedByMe.mockResolvedValue([]);
});

describe("useShareBadges", () => {
  it("returns empty map before data loads", () => {
    activeNodeIds.mockReturnValue(new Promise(() => {}) as never);
    sharedByMe.mockReturnValue(new Promise(() => {}) as never);
    const { result } = renderHook(() => useShareBadges([node("a")]), { wrapper: wrapper() });
    expect(result.current.size).toBe(0);
  });

  it("builds public-link badges only for nodes present in the current list", async () => {
    activeNodeIds.mockResolvedValue(["a", "zzz-not-in-list"]);

    const { result } = renderHook(() => useShareBadges([node("a"), node("b")]), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.size).toBe(1));
    expect(result.current.get("a")).toEqual({ hasPublicLink: true, hasSharedAccess: false });
    expect(result.current.has("b")).toBe(false);
    expect(result.current.has("zzz-not-in-list")).toBe(false);
  });

  it("sets hasSharedAccess from shared-by-me ids", async () => {
    sharedByMe.mockResolvedValue(["a"]);
    const { result } = renderHook(() => useShareBadges([node("a"), node("b")]), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.get("a")?.hasSharedAccess).toBe(true));
    expect(result.current.has("b")).toBe(false);
  });

  it("combines both badges on the same node", async () => {
    activeNodeIds.mockResolvedValue(["a"]);
    sharedByMe.mockResolvedValue(["a"]);
    const { result } = renderHook(() => useShareBadges([node("a")]), { wrapper: wrapper() });
    await waitFor(() =>
      expect(result.current.get("a")).toEqual({ hasPublicLink: true, hasSharedAccess: true }),
    );
  });

  it("returns empty map for empty item list even with active links", async () => {
    activeNodeIds.mockResolvedValue(["a"]);
    sharedByMe.mockResolvedValue(["a"]);
    const { result } = renderHook(() => useShareBadges([]), { wrapper: wrapper() });
    await waitFor(() => expect(activeNodeIds).toHaveBeenCalled());
    expect(result.current.size).toBe(0);
  });
});
