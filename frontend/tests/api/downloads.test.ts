import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { downloadsApi } from "@/api/downloads";

beforeEach(() => vi.clearAllMocks());

describe("downloadsApi", () => {
  it("archiveUrl posts with force_download and filename", async () => {
    const expected = { url: "https://x/a.zip" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await downloadsApi.archiveUrl("task-1", "archive.zip");
    expect(mockApi.post).toHaveBeenCalledWith("/downloads/archive/task-1", null, {
      params: { force_download: true, filename: "archive.zip" },
    });
    expect(result).toEqual(expected);
  });

  it("archiveUrl omits filename when not provided", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await downloadsApi.archiveUrl("task-2");
    expect(mockApi.post).toHaveBeenCalledWith("/downloads/archive/task-2", null, {
      params: { force_download: true },
    });
  });

  it("bulkArchive posts node_ids and archive_name", async () => {
    const expected = { task_id: "t1" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await downloadsApi.bulkArchive(["n1", "n2"], "my.zip");
    expect(mockApi.post).toHaveBeenCalledWith("/downloads/bulk-archive", {
      node_ids: ["n1", "n2"],
      archive_name: "my.zip",
    });
    expect(result).toEqual(expected);
  });

  it("bulkArchive omits archive_name when not provided", async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await downloadsApi.bulkArchive(["n1"]);
    expect(mockApi.post).toHaveBeenCalledWith("/downloads/bulk-archive", {
      node_ids: ["n1"],
    });
  });
});
