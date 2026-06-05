import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { tasksApi } from "@/api/tasks";

beforeEach(() => vi.clearAllMocks());

describe("tasksApi", () => {
  it("list gets /tasks/ with params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { limit: 10, offset: 0, status: "running", task_type: "archive" };
    const result = await tasksApi.list(params);
    expect(mockApi.get).toHaveBeenCalledWith("/tasks/", { params });
    expect(result).toEqual(expected);
  });

  it("list works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await tasksApi.list();
    expect(mockApi.get).toHaveBeenCalledWith("/tasks/", { params: undefined });
  });

  it("get fetches /tasks/:id", async () => {
    const expected = { id: "t1", status: "done" };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await tasksApi.get("t1");
    expect(mockApi.get).toHaveBeenCalledWith("/tasks/t1");
    expect(result).toEqual(expected);
  });

  it("cancel posts reason to /tasks/:id/cancel", async () => {
    const expected = { id: "t1", status: "cancelled" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await tasksApi.cancel("t1", "user request");
    expect(mockApi.post).toHaveBeenCalledWith("/tasks/t1/cancel", { reason: "user request" });
    expect(result).toEqual(expected);
  });

  it("cancel sends null reason when omitted", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await tasksApi.cancel("t1");
    expect(mockApi.post).toHaveBeenCalledWith("/tasks/t1/cancel", { reason: null });
  });
});
