import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { uploadsApi } from "./uploads";

beforeEach(() => vi.clearAllMocks());

describe("uploadsApi", () => {
  it("create posts to /uploads/", async () => {
    const expected = { id: "up1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { filename: "a.bin", size: 100 } as never;
    const result = await uploadsApi.create(data);
    expect(mockApi.post).toHaveBeenCalledWith("/uploads/", data);
    expect(result).toEqual(expected);
  });

  it("getPresignedParts posts to /uploads/:id/parts/presigned", async () => {
    const expected = { parts: [] };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await uploadsApi.getPresignedParts("up1");
    expect(mockApi.post).toHaveBeenCalledWith("/uploads/up1/parts/presigned");
    expect(result).toEqual(expected);
  });

  it("completePart posts to /uploads/:id/parts/:partNumber/complete", async () => {
    const expected = { ok: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { etag: "e1", size: 50 } as never;
    const result = await uploadsApi.completePart("up1", 2, data);
    expect(mockApi.post).toHaveBeenCalledWith("/uploads/up1/parts/2/complete", data);
    expect(result).toEqual(expected);
  });

  it("complete posts to /uploads/:id/complete", async () => {
    const expected = { node_id: "n1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { parts: [{ part_number: 1, etag: "e1" }] } as never;
    const result = await uploadsApi.complete("up1", data);
    expect(mockApi.post).toHaveBeenCalledWith("/uploads/up1/complete", data);
    expect(result).toEqual(expected);
  });

  it("abort posts upload_session_id and reason", async () => {
    const expected = { ok: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await uploadsApi.abort("up1", "cancelled");
    expect(mockApi.post).toHaveBeenCalledWith("/uploads/up1/abort", {
      upload_session_id: "up1",
      reason: "cancelled",
    });
    expect(result).toEqual(expected);
  });

  it("abort sends null reason when omitted", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await uploadsApi.abort("up1");
    expect(mockApi.post).toHaveBeenCalledWith("/uploads/up1/abort", {
      upload_session_id: "up1",
      reason: null,
    });
  });
});
