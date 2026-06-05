import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const run = vi.fn();
vi.mock("@/hooks/useArchiveDownload", () => ({
  useArchiveDownload: () => ({ run, active: false, status: "", progress: 0 }),
}));
vi.mock("@/api/downloads", () => ({ downloadsApi: { bulkArchive: vi.fn() } }));

import { downloadsApi } from "@/api/downloads";
import { useBulkDownload } from "@/hooks/useBulkDownload";
import type { NodeListItem } from "@/types/nodes";

const bulkArchive = vi.mocked(downloadsApi.bulkArchive);

function item(id: string, name: string): NodeListItem {
  return { id, name, node_type: "file" } as NodeListItem;
}

beforeEach(() => {
  vi.clearAllMocks();
  bulkArchive.mockResolvedValue({ task_id: "task-1" } as never);
});

describe("useBulkDownload", () => {
  it("does nothing for empty input", async () => {
    const { result } = renderHook(() => useBulkDownload());
    await act(async () => {
      await result.current.downloadItems([]);
    });
    expect(run).not.toHaveBeenCalled();
  });

  it("uses single item name as archive name", async () => {
    const { result } = renderHook(() => useBulkDownload());
    await act(async () => {
      await result.current.downloadItems([item("n1", "report.pdf")]);
    });
    expect(run).toHaveBeenCalledTimes(1);
    const opts = run.mock.calls[0][0];
    expect(opts.filename).toBe("report.pdf");

    await opts.requestTask();
    expect(bulkArchive).toHaveBeenCalledWith(["n1"], "report.pdf");
  });

  it("uses archive-N name for multiple items and passes all node ids", async () => {
    const { result } = renderHook(() => useBulkDownload());
    await act(async () => {
      await result.current.downloadItems([item("a", "x"), item("b", "y"), item("c", "z")]);
    });
    const opts = run.mock.calls[0][0];
    expect(opts.filename).toBe("archive-3");

    const taskId = await opts.requestTask();
    expect(bulkArchive).toHaveBeenCalledWith(["a", "b", "c"], "archive-3");
    expect(taskId).toBe("task-1");
  });

  it("exposes archive state from useArchiveDownload", () => {
    const { result } = renderHook(() => useBulkDownload());
    expect(result.current.active).toBe(false);
    expect(result.current.status).toBe("");
    expect(result.current.progress).toBe(0);
  });
});
