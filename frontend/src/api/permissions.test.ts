import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { permissionsApi } from "./permissions";

beforeEach(() => vi.clearAllMocks());

describe("permissionsApi", () => {
  it("grant posts to /permissions/grant", async () => {
    const expected = { id: "perm1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { node_id: "n1", user_id: "u1", level: "read" } as never;
    const result = await permissionsApi.grant(data);
    expect(mockApi.post).toHaveBeenCalledWith("/permissions/grant", data);
    expect(result).toEqual(expected);
  });

  it("listForNode gets /permissions/nodes/:id with params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { limit: 10, offset: 0, active_only: true };
    const result = await permissionsApi.listForNode("n1", params);
    expect(mockApi.get).toHaveBeenCalledWith("/permissions/nodes/n1", { params });
    expect(result).toEqual(expected);
  });

  it("listForNode works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await permissionsApi.listForNode("n2");
    expect(mockApi.get).toHaveBeenCalledWith("/permissions/nodes/n2", { params: undefined });
  });

  it("revoke posts to /permissions/revoke", async () => {
    const expected = { id: "perm1", revoked: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { node_id: "n1", user_id: "u1" } as never;
    const result = await permissionsApi.revoke(data);
    expect(mockApi.post).toHaveBeenCalledWith("/permissions/revoke", data);
    expect(result).toEqual(expected);
  });
});
