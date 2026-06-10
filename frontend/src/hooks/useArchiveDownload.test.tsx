import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

vi.mock("@/api/tasks", () => ({ tasksApi: { get: vi.fn() } }));
vi.mock("@/api/downloads", () => ({ downloadsApi: { archiveUrl: vi.fn() } }));
vi.mock("@/lib/download", () => ({ downloadBlobFromUrl: vi.fn() }));
// Убираем реальные задержки polling, чтобы тесты были быстрыми.
vi.mock("@/lib/constants", () => ({
  ARCHIVE_POLL_MS: 0,
  ARCHIVE_TIMEOUT_MS: 15 * 60 * 1000,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  }),
}));

import { tasksApi } from "@/api/tasks";
import { downloadsApi } from "@/api/downloads";
import { downloadBlobFromUrl } from "@/lib/download";
import { toast } from "sonner";
import { useArchiveDownload } from "./useArchiveDownload";

const tasksGet = vi.mocked(tasksApi.get);
const archiveUrl = vi.mocked(downloadsApi.archiveUrl);
const dlBlob = vi.mocked(downloadBlobFromUrl);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(toast.loading).mockReturnValue("toast-1" as never);
});

describe("useArchiveDownload", () => {
  it("starts in idle state", () => {
    const { result } = renderHook(() => useArchiveDownload());
    expect(result.current.active).toBe(false);
    expect(result.current.status).toBe("");
    expect(result.current.progress).toBe(0);
    expect(result.current.activeId).toBeNull();
  });

  it("runs the full happy path: poll, get url, download, success toast", async () => {
    tasksGet
      .mockResolvedValueOnce({ status: "running" } as never)
      .mockResolvedValueOnce({ status: "completed" } as never);
    archiveUrl.mockResolvedValue({ presigned_url: "https://x/a.zip", filename: "a.zip" } as never);

    const onSuccess = vi.fn();
    const { result } = renderHook(() => useArchiveDownload());

    await act(async () => {
      await result.current.run({
        requestTask: async () => "task-1",
        filename: "a",
        activeId: "node-1",
        onSuccess,
      });
    });

    expect(tasksGet).toHaveBeenCalledWith("task-1");
    expect(archiveUrl).toHaveBeenCalledWith("task-1", "a.zip");
    expect(dlBlob).toHaveBeenCalledWith("https://x/a.zip", "a.zip");
    expect(toast.success).toHaveBeenCalledWith("«a» скачивается", { id: "toast-1" });
    expect(onSuccess).toHaveBeenCalled();
    // finally сбрасывает состояние.
    expect(result.current.active).toBe(false);
    expect(result.current.activeId).toBeNull();
  });

  it("falls back to `${filename}.zip` when api omits filename", async () => {
    tasksGet.mockResolvedValueOnce({ status: "completed" } as never);
    archiveUrl.mockResolvedValue({ presigned_url: "https://x/b" } as never);

    const { result } = renderHook(() => useArchiveDownload());
    await act(async () => {
      await result.current.run({ requestTask: async () => "t2", filename: "doc" });
    });
    expect(dlBlob).toHaveBeenCalledWith("https://x/b", "doc.zip");
  });

  it("shows error toast when task fails with error_message", async () => {
    tasksGet.mockResolvedValueOnce({
      status: "failed",
      error_message: "boom",
    } as never);

    const { result } = renderHook(() => useArchiveDownload());
    await act(async () => {
      await result.current.run({ requestTask: async () => "t3", filename: "x" });
    });

    expect(toast.error).toHaveBeenCalledWith("Не удалось скачать «x»: boom", { id: "toast-1" });
    expect(archiveUrl).not.toHaveBeenCalled();
    expect(result.current.active).toBe(false);
  });

  it("uses default message when failed task has no error_message", async () => {
    tasksGet.mockResolvedValueOnce({ status: "failed" } as never);
    const { result } = renderHook(() => useArchiveDownload());
    await act(async () => {
      await result.current.run({ requestTask: async () => "t4", filename: "y" });
    });
    expect(toast.error).toHaveBeenCalledWith(
      "Не удалось скачать «y»: Архивация завершилась с ошибкой",
      { id: "toast-1" },
    );
  });

  it("handles cancelled status as a non-completed failure", async () => {
    tasksGet.mockResolvedValueOnce({ status: "cancelled" } as never);
    const { result } = renderHook(() => useArchiveDownload());
    await act(async () => {
      await result.current.run({ requestTask: async () => "t5", filename: "z" });
    });
    expect(toast.error).toHaveBeenCalled();
    expect(archiveUrl).not.toHaveBeenCalled();
  });

  it("reports requestTask rejection through error toast", async () => {
    const { result } = renderHook(() => useArchiveDownload());
    await act(async () => {
      await result.current.run({
        requestTask: async () => {
          throw new Error("no task");
        },
        filename: "q",
      });
    });
    expect(toast.error).toHaveBeenCalledWith("Не удалось скачать «q»: no task", { id: "toast-1" });
  });

  it("handles non-Error throw with fallback message", async () => {
    const { result } = renderHook(() => useArchiveDownload());
    await act(async () => {
      await result.current.run({
        requestTask: async () => {
          throw "string failure";
        },
        filename: "q2",
      });
    });
    expect(toast.error).toHaveBeenCalledWith("Не удалось скачать «q2»: Неизвестная ошибка", {
      id: "toast-1",
    });
  });

  it("ignores re-entrant run while already active", async () => {
    let resolveTask: (v: string) => void = () => {};
    tasksGet.mockResolvedValue({ status: "completed" } as never);
    archiveUrl.mockResolvedValue({ presigned_url: "u", filename: "f" } as never);

    const { result } = renderHook(() => useArchiveDownload());

    let firstRun: Promise<void>;
    act(() => {
      firstRun = result.current.run({
        requestTask: () => new Promise<string>((r) => (resolveTask = r)),
        filename: "first",
      });
    });

    await waitFor(() => expect(result.current.active).toBe(true));

    // Второй вызов во время активного должен немедленно вернуться.
    await act(async () => {
      await result.current.run({ requestTask: async () => "other", filename: "second" });
    });
    // requestTask первого ещё не разрешён, второй toast.loading не должен добавиться.
    expect(vi.mocked(toast.loading).mock.calls.filter((c) => String(c[0]).includes("second"))).toHaveLength(0);

    await act(async () => {
      resolveTask("task-x");
      await firstRun!;
    });
    expect(toast.success).toHaveBeenCalled();
  });
});
