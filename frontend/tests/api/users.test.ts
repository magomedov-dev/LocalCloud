import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { usersApi } from "@/api/users";

beforeEach(() => vi.clearAllMocks());

describe("usersApi", () => {
  it("list gets /users with params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { limit: 10, offset: 0, status: "active", search: "joe" };
    const result = await usersApi.list(params);
    expect(mockApi.get).toHaveBeenCalledWith("/users", { params });
    expect(result).toEqual(expected);
  });

  it("list works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await usersApi.list();
    expect(mockApi.get).toHaveBeenCalledWith("/users", { params: undefined });
  });

  it("get fetches /users/:id", async () => {
    const expected = { id: "u1" };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await usersApi.get("u1");
    expect(mockApi.get).toHaveBeenCalledWith("/users/u1");
    expect(result).toEqual(expected);
  });

  it("block posts reason to /users/:id/block", async () => {
    const expected = { id: "u1", status: "blocked" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await usersApi.block("u1", "abuse");
    expect(mockApi.post).toHaveBeenCalledWith("/users/u1/block", { block_reason: "abuse" });
    expect(result).toEqual(expected);
  });

  it("block sends null reason when omitted", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await usersApi.block("u1");
    expect(mockApi.post).toHaveBeenCalledWith("/users/u1/block", { block_reason: null });
  });

  it("unblock posts to /users/:id/unblock", async () => {
    const expected = { id: "u1", status: "active" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await usersApi.unblock("u1");
    expect(mockApi.post).toHaveBeenCalledWith("/users/u1/unblock");
    expect(result).toEqual(expected);
  });

  it("approve posts to /users/:id/approve", async () => {
    const expected = { id: "u1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await usersApi.approve("u1");
    expect(mockApi.post).toHaveBeenCalledWith("/users/u1/approve");
    expect(result).toEqual(expected);
  });

  it("reject posts rejection_reason to /users/:id/reject", async () => {
    const expected = { id: "u1", status: "rejected" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await usersApi.reject("u1", "incomplete");
    expect(mockApi.post).toHaveBeenCalledWith("/users/u1/reject", {
      rejection_reason: "incomplete",
    });
    expect(result).toEqual(expected);
  });

  it("delete deletes /users/:id", async () => {
    const expected = { id: "u1", deleted: true };
    mockApi.delete.mockResolvedValueOnce({ data: expected });
    const result = await usersApi.delete("u1");
    expect(mockApi.delete).toHaveBeenCalledWith("/users/u1");
    expect(result).toEqual(expected);
  });

  it("changePassword posts new_password", async () => {
    const expected = { id: "u1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await usersApi.changePassword("u1", "newpw");
    expect(mockApi.post).toHaveBeenCalledWith("/users/u1/change-password", {
      new_password: "newpw",
    });
    expect(result).toEqual(expected);
  });
});
