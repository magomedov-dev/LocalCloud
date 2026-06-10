import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { foldersApi } from "./folders";

beforeEach(() => vi.clearAllMocks());

describe("foldersApi", () => {
  it("create posts to /folders/", async () => {
    const expected = { id: "f1", name: "Docs" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { name: "Docs", parent_id: null } as never;
    const result = await foldersApi.create(data);
    expect(mockApi.post).toHaveBeenCalledWith("/folders/", data);
    expect(result).toEqual(expected);
  });

  it("archive posts with archive_name", async () => {
    const expected = { task_id: "t1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await foldersApi.archive("f1", "custom.zip");
    expect(mockApi.post).toHaveBeenCalledWith("/folders/f1/archive", {
      folder_id: "f1",
      archive_name: "custom.zip",
      include_deleted: false,
    });
    expect(result).toEqual(expected);
  });

  it("archive sends null archive_name when omitted", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await foldersApi.archive("f2");
    expect(mockApi.post).toHaveBeenCalledWith("/folders/f2/archive", {
      folder_id: "f2",
      archive_name: null,
      include_deleted: false,
    });
  });
});
