import type { ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeTestQueryClient } from "@tests/utils";

vi.mock("@/api/quotas", () => ({ quotasApi: { me: vi.fn() } }));

import { quotasApi } from "@/api/quotas";
import { useMyQuota, formatBytes } from "@/hooks/useQuota";

const me = vi.mocked(quotasApi.me);

function wrapper() {
  const qc = makeTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => vi.clearAllMocks());

describe("useMyQuota", () => {
  it("fetches current user quota", async () => {
    me.mockResolvedValue({ used_bytes: 100, quota_bytes: 1000 } as never);
    const { result } = renderHook(() => useMyQuota(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(me).toHaveBeenCalled();
    expect(result.current.data).toEqual({ used_bytes: 100, quota_bytes: 1000 });
  });

  it("surfaces fetch error", async () => {
    me.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useMyQuota(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toBe("boom");
  });
});

describe("formatBytes", () => {
  it("formats zero", () => {
    expect(formatBytes(0)).toBe("0 Б");
  });
  it("formats bytes without decimals", () => {
    expect(formatBytes(512)).toBe("512 Б");
  });
  it("formats kilobytes with one decimal", () => {
    expect(formatBytes(1536)).toBe("1.5 КБ");
  });
  it("formats megabytes", () => {
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 МБ");
  });
  it("formats gigabytes", () => {
    expect(formatBytes(3 * 1024 * 1024 * 1024)).toBe("3.0 ГБ");
  });
  it("formats terabytes", () => {
    expect(formatBytes(2 * 1024 ** 4)).toBe("2.0 ТБ");
  });
});
