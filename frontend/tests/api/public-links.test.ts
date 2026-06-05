import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { publicLinksApi } from "@/api/public-links";

beforeEach(() => vi.clearAllMocks());

describe("publicLinksApi", () => {
  it("create posts to /public-links/", async () => {
    const expected = { id: "pl1", token: "tok" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { node_id: "n1" } as never;
    const result = await publicLinksApi.create(data);
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/", data);
    expect(result).toEqual(expected);
  });

  it("list gets /public-links/ with params", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const params = { limit: 10, offset: 0, node_id: "n1", is_active: true };
    const result = await publicLinksApi.list(params);
    expect(mockApi.get).toHaveBeenCalledWith("/public-links/", { params });
    expect(result).toEqual(expected);
  });

  it("list works without params", async () => {
    mockApi.get.mockResolvedValueOnce({ data: { items: [] } });
    await publicLinksApi.list();
    expect(mockApi.get).toHaveBeenCalledWith("/public-links/", { params: undefined });
  });

  it("listForNode gets /public-links/ with node filters", async () => {
    const expected = { items: [], total: 0 };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await publicLinksApi.listForNode("n1");
    expect(mockApi.get).toHaveBeenCalledWith("/public-links/", {
      params: { node_id: "n1", is_active: true, limit: 10 },
    });
    expect(result).toEqual(expected);
  });

  it("get fetches /public-links/:id", async () => {
    const expected = { id: "pl1" };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await publicLinksApi.get("pl1");
    expect(mockApi.get).toHaveBeenCalledWith("/public-links/pl1");
    expect(result).toEqual(expected);
  });

  it("update patches /public-links/:id", async () => {
    const expected = { id: "pl1", updated: true };
    mockApi.patch.mockResolvedValueOnce({ data: expected });
    const data = { password: "secret" } as never;
    const result = await publicLinksApi.update("pl1", data);
    expect(mockApi.patch).toHaveBeenCalledWith("/public-links/pl1", data);
    expect(result).toEqual(expected);
  });

  it("getPublic fetches /public-links/public/:token", async () => {
    const expected = { token: "tok" };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await publicLinksApi.getPublic("tok");
    expect(mockApi.get).toHaveBeenCalledWith("/public-links/public/tok");
    expect(result).toEqual(expected);
  });

  it("validateAccess posts token and password", async () => {
    const expected = { granted: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await publicLinksApi.validateAccess("tok", "pw");
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/public/tok/access", {
      token: "tok",
      password: "pw",
    });
    expect(result).toEqual(expected);
  });

  it("validateAccess sends null password when omitted", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await publicLinksApi.validateAccess("tok");
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/public/tok/access", {
      token: "tok",
      password: null,
    });
  });

  it("download posts token and password", async () => {
    const expected = { url: "u" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await publicLinksApi.download("tok", "pw");
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/public/tok/download", {
      token: "tok",
      password: "pw",
    });
    expect(result).toEqual(expected);
  });

  it("download sends null password when omitted", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await publicLinksApi.download("tok");
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/public/tok/download", {
      token: "tok",
      password: null,
    });
  });

  it("revoke posts to /public-links/:id/revoke with data", async () => {
    const expected = { id: "pl1", revoked: true };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { reason: "spam" } as never;
    const result = await publicLinksApi.revoke("pl1", data);
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/pl1/revoke", data);
    expect(result).toEqual(expected);
  });

  it("revoke defaults data to empty object", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await publicLinksApi.revoke("pl1");
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/pl1/revoke", {});
  });

  it("startFolderArchive posts token and password", async () => {
    const expected = { task_id: "t1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await publicLinksApi.startFolderArchive("tok", "pw");
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/public/tok/folder-download", {
      token: "tok",
      password: "pw",
    });
    expect(result).toEqual(expected);
  });

  it("startFolderArchive sends null password when omitted", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await publicLinksApi.startFolderArchive("tok");
    expect(mockApi.post).toHaveBeenCalledWith("/public-links/public/tok/folder-download", {
      token: "tok",
      password: null,
    });
  });

  it("pollFolderArchive gets folder-download status", async () => {
    const expected = { status: "ready" };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await publicLinksApi.pollFolderArchive("tok", "task-1");
    expect(mockApi.get).toHaveBeenCalledWith(
      "/public-links/public/tok/folder-download/task-1",
    );
    expect(result).toEqual(expected);
  });
});
