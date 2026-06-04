import type { ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeTestQueryClient } from "@tests/utils";

vi.mock("@/api/config", () => ({ configApi: { get: vi.fn() } }));

import { configApi } from "@/api/config";
import { useFeatures } from "@/hooks/useFeatures";

const getConfig = vi.mocked(configApi.get);

function wrapper() {
  const qc = makeTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useFeatures", () => {
  it("returns all-enabled defaults before config loads", () => {
    getConfig.mockReturnValue(new Promise(() => {}) as never);
    const { result } = renderHook(() => useFeatures(), { wrapper: wrapper() });
    expect(result.current).toEqual({
      previews_enabled: true,
      file_viewer_enabled: true,
      media_playback_enabled: true,
      file_editing_enabled: true,
    });
  });

  it("returns flags from the backend once loaded", async () => {
    getConfig.mockResolvedValue({
      features: {
        previews_enabled: false,
        file_viewer_enabled: true,
        media_playback_enabled: false,
        file_editing_enabled: false,
      },
    });
    const { result } = renderHook(() => useFeatures(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.previews_enabled).toBe(false));
    expect(result.current).toEqual({
      previews_enabled: false,
      file_viewer_enabled: true,
      media_playback_enabled: false,
      file_editing_enabled: false,
    });
  });

  it("falls back to defaults when the request fails", async () => {
    getConfig.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useFeatures(), { wrapper: wrapper() });
    await waitFor(() => expect(getConfig).toHaveBeenCalled());
    expect(result.current.file_viewer_enabled).toBe(true);
  });
});
