import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { registrationApi } from "@/api/registration";

beforeEach(() => vi.clearAllMocks());

describe("registrationApi", () => {
  it("create posts to /registration/requests", async () => {
    const expected = { id: "req1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { email: "u@e.com", username: "u", password: "pw" } as never;
    const result = await registrationApi.create(data);
    expect(mockApi.post).toHaveBeenCalledWith("/registration/requests", data);
    expect(result).toEqual(expected);
  });

  it("list gets /registration/requests with params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { limit: 10, offset: 0, status: "pending" };
    const result = await registrationApi.list(params);
    expect(mockApi.get).toHaveBeenCalledWith("/registration/requests", { params });
    expect(result).toEqual(expected);
  });

  it("list works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await registrationApi.list();
    expect(mockApi.get).toHaveBeenCalledWith("/registration/requests", { params: undefined });
  });

  it("approve posts to approve endpoint with data", async () => {
    const expected = { id: "req1", user_id: "u1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { is_email_verified: true } as never;
    const result = await registrationApi.approve("req1", data);
    expect(mockApi.post).toHaveBeenCalledWith("/registration/requests/req1/approve", data);
    expect(result).toEqual(expected);
  });

  it("approve defaults data to empty object", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await registrationApi.approve("req1");
    expect(mockApi.post).toHaveBeenCalledWith("/registration/requests/req1/approve", {});
  });

  it("reject posts to reject endpoint", async () => {
    const expected = { ok: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { reason: "spam" } as never;
    const result = await registrationApi.reject("req1", data);
    expect(mockApi.post).toHaveBeenCalledWith("/registration/requests/req1/reject", data);
    expect(result).toEqual(expected);
  });
});
