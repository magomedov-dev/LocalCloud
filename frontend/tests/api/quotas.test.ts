import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { quotasApi } from "@/api/quotas";

beforeEach(() => vi.clearAllMocks());

describe("quotasApi", () => {
  it("me gets /quotas/me", async () => {
    const expected = { used: 1, limit: 10 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await quotasApi.me();
    expect(mockApi.get).toHaveBeenCalledWith("/quotas/me");
    expect(result).toEqual(expected);
  });

  it("getByUserId gets /quotas/users/:id", async () => {
    const expected = { used: 5 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await quotasApi.getByUserId("u1");
    expect(mockApi.get).toHaveBeenCalledWith("/quotas/users/u1");
    expect(result).toEqual(expected);
  });

  it("updateByUserId puts to /quotas/users/:id", async () => {
    const expected = { limit: 20 };
    mockApi.put.mockResolvedValueOnce({ data: expected });
    const data = { storage_limit: 20 } as never;
    const result = await quotasApi.updateByUserId("u1", data);
    expect(mockApi.put).toHaveBeenCalledWith("/quotas/users/u1", data);
    expect(result).toEqual(expected);
  });

  it("serverStorage gets /quotas/server-storage", async () => {
    const expected = { total: 100 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await quotasApi.serverStorage();
    expect(mockApi.get).toHaveBeenCalledWith("/quotas/server-storage");
    expect(result).toEqual(expected);
  });

  it("listIncreaseRequests gets with params", async () => {
    const expected = [{ id: "r1" }];
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { status: "pending" as never, limit: 10, offset: 0 };
    const result = await quotasApi.listIncreaseRequests(params);
    expect(mockApi.get).toHaveBeenCalledWith("/quotas/increase-requests", { params });
    expect(result).toEqual(expected);
  });

  it("listIncreaseRequests works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: [] });
    await quotasApi.listIncreaseRequests();
    expect(mockApi.get).toHaveBeenCalledWith("/quotas/increase-requests", { params: undefined });
  });

  it("approveIncreaseRequest posts to approve endpoint", async () => {
    const expected = { id: "r1", status: "approved" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await quotasApi.approveIncreaseRequest("r1");
    expect(mockApi.post).toHaveBeenCalledWith("/quotas/increase-requests/r1/approve");
    expect(result).toEqual(expected);
  });

  it("rejectIncreaseRequest posts comment to reject endpoint", async () => {
    const expected = { id: "r1", status: "rejected" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await quotasApi.rejectIncreaseRequest("r1", { admin_comment: "no" });
    expect(mockApi.post).toHaveBeenCalledWith("/quotas/increase-requests/r1/reject", {
      admin_comment: "no",
    });
    expect(result).toEqual(expected);
  });

  it("rejectIncreaseRequest accepts null comment", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await quotasApi.rejectIncreaseRequest("r1", { admin_comment: null });
    expect(mockApi.post).toHaveBeenCalledWith("/quotas/increase-requests/r1/reject", {
      admin_comment: null,
    });
  });
});
