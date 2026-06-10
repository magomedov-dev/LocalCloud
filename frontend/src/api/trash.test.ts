import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { trashApi } from "./trash";

beforeEach(() => vi.clearAllMocks());

describe("trashApi", () => {
  it("list gets /trash/ with params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { limit: 10, offset: 0 };
    const result = await trashApi.list(params);
    expect(mockApi.get).toHaveBeenCalledWith("/trash/", { params });
    expect(result).toEqual(expected);
  });

  it("list works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await trashApi.list();
    expect(mockApi.get).toHaveBeenCalledWith("/trash/", { params: undefined });
  });

  it("restore posts trash_item_id merged with data", async () => {
    const expected = { restored: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await trashApi.restore("ti1", { target_folder_id: "f1" } as never);
    expect(mockApi.post).toHaveBeenCalledWith("/trash/ti1/restore", {
      trash_item_id: "ti1",
      target_folder_id: "f1",
    });
    expect(result).toEqual(expected);
  });

  it("restore works without data", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await trashApi.restore("ti1");
    expect(mockApi.post).toHaveBeenCalledWith("/trash/ti1/restore", {
      trash_item_id: "ti1",
    });
  });

  it("purge posts to /trash/:id/purge", async () => {
    const expected = { purged: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await trashApi.purge("ti1");
    expect(mockApi.post).toHaveBeenCalledWith("/trash/ti1/purge", {});
    expect(result).toEqual(expected);
  });

  it("empty posts to /trash/empty", async () => {
    const expected = { count: 3 };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await trashApi.empty();
    expect(mockApi.post).toHaveBeenCalledWith("/trash/empty", {});
    expect(result).toEqual(expected);
  });
});
