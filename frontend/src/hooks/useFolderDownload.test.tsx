import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const run = vi.fn();
let currentActiveId: string | null = null;
vi.mock("./useArchiveDownload", () => ({
  useArchiveDownload: () => ({ run, activeId: currentActiveId }),
}));
vi.mock("@/api/nodes", () => ({ nodesApi: { content: vi.fn() } }));
vi.mock("@/api/folders", () => ({ foldersApi: { archive: vi.fn() } }));

const invalidateQueries = vi.fn();
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries }),
}));

import { nodesApi } from "@/api/nodes";
import { foldersApi } from "@/api/folders";
import { useFolderDownload } from "./useFolderDownload";

const content = vi.mocked(nodesApi.content);
const archive = vi.mocked(foldersApi.archive);

beforeEach(() => {
  vi.clearAllMocks();
  currentActiveId = null;
  content.mockResolvedValue({ folder: { id: "folder-meta-1" } } as never);
  archive.mockResolvedValue({ task_id: "task-9" } as never);
});

describe("useFolderDownload", () => {
  it("requests task via node content -> folder archive", async () => {
    const { result } = renderHook(() => useFolderDownload());
    await act(async () => {
      await result.current.downloadFolder("node-1", "My Folder");
    });

    expect(run).toHaveBeenCalledTimes(1);
    const opts = run.mock.calls[0][0];
    expect(opts.activeId).toBe("node-1");
    expect(opts.filename).toBe("My Folder");

    const taskId = await opts.requestTask();
    expect(content).toHaveBeenCalledWith("node-1");
    expect(archive).toHaveBeenCalledWith("folder-meta-1", "My Folder");
    expect(taskId).toBe("task-9");
  });

  it("onSuccess invalidates the node content query", async () => {
    const { result } = renderHook(() => useFolderDownload());
    await act(async () => {
      await result.current.downloadFolder("node-2", "F2");
    });
    const opts = run.mock.calls[0][0];
    opts.onSuccess();
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["nodes", "node-2", "content"],
    });
  });

  it("exposes downloading id from archive hook activeId", () => {
    currentActiveId = "node-active";
    const { result } = renderHook(() => useFolderDownload());
    expect(result.current.downloading).toBe("node-active");
  });
});
