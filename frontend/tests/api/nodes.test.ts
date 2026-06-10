import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { nodesApi } from "@/api/nodes";

beforeEach(() => vi.clearAllMocks());

describe("nodesApi", () => {
  it("list gets /nodes/ with params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { parent_id: "p1", limit: 20, offset: 0 };
    const result = await nodesApi.list(params);
    expect(mockApi.get).toHaveBeenCalledWith("/nodes/", { params });
    expect(result).toEqual(expected);
  });

  it("list works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await nodesApi.list();
    expect(mockApi.get).toHaveBeenCalledWith("/nodes/", { params: undefined });
  });

  it("content gets /nodes/:id/content with params", async () => {
    const expected = { folder: {}, items: [] };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await nodesApi.content("n1", { limit: 5, offset: 10 });
    expect(mockApi.get).toHaveBeenCalledWith("/nodes/n1/content", {
      params: { limit: 5, offset: 10 },
    });
    expect(result).toEqual(expected);
  });

  it("rename posts new name", async () => {
    const expected = { ok: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await nodesApi.rename("n1", "New Name");
    expect(mockApi.post).toHaveBeenCalledWith("/nodes/n1/rename", { name: "New Name" });
    expect(result).toEqual(expected);
  });

  it("download posts with force_download default true", async () => {
    const expected = { url: "u" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await nodesApi.download("n1");
    expect(mockApi.post).toHaveBeenCalledWith(
      "/nodes/n1/download",
      {},
      { params: { force_download: true } },
    );
    expect(result).toEqual(expected);
  });

  it("download honors explicit forceDownload false", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await nodesApi.download("n1", false);
    expect(mockApi.post).toHaveBeenCalledWith(
      "/nodes/n1/download",
      {},
      { params: { force_download: false } },
    );
  });

  it("thumbnail gets /nodes/:id/thumbnail", async () => {
    const expected = { url: "thumb" };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await nodesApi.thumbnail("n1");
    expect(mockApi.get).toHaveBeenCalledWith("/nodes/n1/thumbnail");
    expect(result).toEqual(expected);
  });

  it("thumbnailsBatch posts node_ids and returns thumbnails map", async () => {
    const thumbnails = { n1: "u1", n2: null };
    mockApi.post.mockResolvedValueOnce({ data: { thumbnails } });
    const controller = new AbortController();
    const result = await nodesApi.thumbnailsBatch(["n1", "n2"], controller.signal);
    expect(mockApi.post).toHaveBeenCalledWith(
      "/nodes/thumbnails/batch",
      { node_ids: ["n1", "n2"] },
      { signal: controller.signal },
    );
    expect(result).toEqual(thumbnails);
  });

  it("thumbnailsBatch works without signal", async () => {
    mockApi.post.mockResolvedValueOnce({ data: { thumbnails: {} } });
    const result = await nodesApi.thumbnailsBatch(["n1"]);
    expect(mockApi.post).toHaveBeenCalledWith(
      "/nodes/thumbnails/batch",
      { node_ids: ["n1"] },
      { signal: undefined },
    );
    expect(result).toEqual({});
  });

  it("softDelete deletes /nodes/:id", async () => {
    const expected = { ok: true };
    mockApi.delete.mockResolvedValueOnce({ data: expected });
    const result = await nodesApi.softDelete("n1");
    expect(mockApi.delete).toHaveBeenCalledWith("/nodes/n1");
    expect(result).toEqual(expected);
  });

  it("search gets /nodes/search with query merged into params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await nodesApi.search("report", { limit: 10, offset: 0 });
    expect(mockApi.get).toHaveBeenCalledWith("/nodes/search", {
      params: { query: "report", limit: 10, offset: 0 },
    });
    expect(result).toEqual(expected);
  });

  it("search works without extra params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await nodesApi.search("foo");
    expect(mockApi.get).toHaveBeenCalledWith("/nodes/search", {
      params: { query: "foo" },
    });
  });

  it("move posts move data", async () => {
    const expected = { ok: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { parent_id: "p2" } as never;
    const result = await nodesApi.move("n1", data);
    expect(mockApi.post).toHaveBeenCalledWith("/nodes/n1/move", data);
    expect(result).toEqual(expected);
  });

  it("streamUrl builds the stream URL", () => {
    expect(nodesApi.streamUrl("n1")).toBe("/api/v1/nodes/n1/stream");
  });
});
