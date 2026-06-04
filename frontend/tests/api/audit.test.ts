import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { auditApi } from "@/api/audit";

beforeEach(() => vi.clearAllMocks());

describe("auditApi", () => {
  it("list calls GET /audit/logs with params and returns data", async () => {
    const expected = { items: [{ id: "a1" }], total: 1 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { limit: 10, offset: 0, action: "login" };
    const result = await auditApi.list(params);
    expect(mockApi.get).toHaveBeenCalledWith("/audit/logs", { params });
    expect(result).toEqual(expected);
  });

  it("list works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await auditApi.list();
    expect(mockApi.get).toHaveBeenCalledWith("/audit/logs", { params: undefined });
  });
});
