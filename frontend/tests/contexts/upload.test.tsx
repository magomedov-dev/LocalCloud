import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeTestQueryClient } from "@tests/utils";
import { UploadProvider } from "@/contexts/upload";
import { useUpload } from "@/contexts/upload-context";

vi.mock("@/api/uploads", () => ({
  uploadsApi: {
    create: vi.fn(),
    getPresignedParts: vi.fn(),
    completePart: vi.fn(),
    complete: vi.fn(),
    abort: vi.fn(),
  },
}));

vi.mock("@/lib/folderCache", () => ({
  insertNodeIntoFolderCache: vi.fn(),
}));

import { uploadsApi } from "@/api/uploads";
import { insertNodeIntoFolderCache } from "@/lib/folderCache";

const createMock = vi.mocked(uploadsApi.create);
const partsMock = vi.mocked(uploadsApi.getPresignedParts);
const completePartMock = vi.mocked(uploadsApi.completePart);
const completeMock = vi.mocked(uploadsApi.complete);
const abortMock = vi.mocked(uploadsApi.abort);
const insertMock = vi.mocked(insertNodeIntoFolderCache);

const QKEY = ["nodes", "folder-1"];

/** Создаёт ответ fetch с заданным статусом и ETag. */
function fetchResponse(ok: boolean, status = 200, etag = "etag-123") {
  return {
    ok,
    status,
    headers: { get: (name: string) => (name.toLowerCase() === "etag" ? `"${etag}"` : null) },
  };
}

function setup() {
  const queryClient = makeTestQueryClient();
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <UploadProvider>{children}</UploadProvider>
    </QueryClientProvider>
  );
  const { result } = renderHook(() => useUpload(), { wrapper });
  return { result, queryClient, invalidateSpy };
}

function makeFile(name = "photo.png", size = 10, type = "image/png") {
  return new File([new Uint8Array(size)], name, { type });
}

beforeEach(() => {
  vi.clearAllMocks();
  createMock.mockResolvedValue({ id: "session-1" } as never);
  partsMock.mockResolvedValue({
    parts: [{ part_number: 1, url: "https://minio/put/1", headers: {} }],
  } as never);
  completePartMock.mockResolvedValue({} as never);
  completeMock.mockResolvedValue({ node_id: "node-1" } as never);
  abortMock.mockResolvedValue({} as never);
  globalThis.fetch = vi.fn().mockResolvedValue(fetchResponse(true)) as never;
});

describe("UploadProvider", () => {
  it("проходит жизненный цикл pending -> uploading -> done", async () => {
    const { result, invalidateSpy } = setup();
    const file = makeFile();

    act(() => result.current.enqueue([file], "parent-1", QKEY));

    // Сразу после enqueue задача добавлена.
    expect(result.current.tasks).toHaveLength(1);
    const id = result.current.tasks[0].id;
    expect(result.current.tasks[0].filename).toBe("photo.png");

    await waitFor(() => expect(result.current.tasks[0].status).toBe("done"));
    const task = result.current.tasks.find((t) => t.id === id)!;
    expect(task.progress).toBe(100);
    expect(task.error).toBeNull();

    // API-вызовы прошли в правильном порядке.
    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({
        parent_node_id: "parent-1",
        filename: "photo.png",
        parts_count: 1,
      }),
    );
    expect(partsMock).toHaveBeenCalledWith("session-1");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "https://minio/put/1",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(completePartMock).toHaveBeenCalledWith("session-1", 1, {
      part_number: 1,
      etag: "etag-123",
      size_bytes: 10,
    });
    expect(completeMock).toHaveBeenCalledWith("session-1", {
      upload_session_id: "session-1",
      parts: [{ part_number: 1, etag: "etag-123", size_bytes: 10 }],
    });

    // Оптимистичная вставка в кэш папки.
    expect(insertMock).toHaveBeenCalledWith(
      expect.anything(),
      QKEY,
      expect.objectContaining({ id: "node-1", name: "photo.png", node_type: "file" }),
    );

    // После завершения пачки инвалидируются ключ папки и квота.
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: QKEY });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["quota", "me"] });
    });
    expect(abortMock).not.toHaveBeenCalled();
  });

  it("отбрасывает запрещённые заголовки в presigned PUT", async () => {
    partsMock.mockResolvedValueOnce({
      parts: [
        {
          part_number: 1,
          url: "https://minio/put/1",
          headers: { "Content-Length": "10", "x-amz-meta": "ok", Host: "h" },
        },
      ],
    } as never);
    const { result } = setup();

    act(() => result.current.enqueue([makeFile()], "parent-1", QKEY));
    await waitFor(() => expect(result.current.tasks[0].status).toBe("done"));

    const fetchArgs = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(fetchArgs.headers).toEqual({ "x-amz-meta": "ok" });
  });

  it("переводит задачу в error без parentNodeId (UserFacingError)", async () => {
    const { result } = setup();

    act(() => result.current.enqueue([makeFile()], null, QKEY));

    await waitFor(() => expect(result.current.tasks[0].status).toBe("error"));
    expect(result.current.tasks[0].error).toBe("Выберите папку для загрузки файлов");
    expect(createMock).not.toHaveBeenCalled();
    expect(abortMock).not.toHaveBeenCalled();
  });

  it("переводит задачу в error при неуспешном PUT и отменяет сессию", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(fetchResponse(false, 500)) as never;
    const { result } = setup();

    act(() => result.current.enqueue([makeFile()], "parent-1", QKEY));

    await waitFor(() => expect(result.current.tasks[0].status).toBe("error"));
    expect(result.current.tasks[0].error).toBeTruthy();
    // Сессия уже создана -> abort вызван для освобождения слота.
    expect(abortMock).toHaveBeenCalledWith("session-1");
    expect(completeMock).not.toHaveBeenCalled();
  });

  it("не падает, если abort после ошибки тоже бросает", async () => {
    completeMock.mockRejectedValueOnce(new Error("complete failed"));
    abortMock.mockRejectedValueOnce(new Error("abort failed"));
    const { result } = setup();

    act(() => result.current.enqueue([makeFile()], "parent-1", QKEY));

    await waitFor(() => expect(result.current.tasks[0].status).toBe("error"));
    expect(abortMock).toHaveBeenCalledWith("session-1");
  });

  it("повторяет создание сессии при ошибке квоты", async () => {
    const quotaErr = { response: { data: { message: "quota exceeded" } } };
    createMock
      .mockRejectedValueOnce(quotaErr)
      .mockResolvedValueOnce({ id: "session-retry" } as never);
    const { result } = setup();

    act(() => result.current.enqueue([makeFile()], "parent-1", QKEY));

    await waitFor(() => expect(result.current.tasks[0].status).toBe("done"), { timeout: 5000 });
    expect(createMock).toHaveBeenCalledTimes(2);
    expect(partsMock).toHaveBeenCalledWith("session-retry");
  }, 10000);

  it("обрабатывает несколько частей с обновлением прогресса", async () => {
    partsMock.mockResolvedValueOnce({
      parts: [
        { part_number: 1, url: "https://minio/put/1", headers: {} },
        { part_number: 2, url: "https://minio/put/2", headers: {} },
      ],
    } as never);
    const { result } = setup();

    act(() => result.current.enqueue([makeFile("big.bin", 20)], "parent-1", QKEY));

    await waitFor(() => expect(result.current.tasks[0].status).toBe("done"));
    expect(completePartMock).toHaveBeenCalledTimes(2);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(result.current.tasks[0].progress).toBe(100);
  });

  it("не вставляет в кэш, если complete не вернул node_id", async () => {
    completeMock.mockResolvedValueOnce({ node_id: null } as never);
    const { result } = setup();

    act(() => result.current.enqueue([makeFile()], "parent-1", QKEY));
    await waitFor(() => expect(result.current.tasks[0].status).toBe("done"));
    expect(insertMock).not.toHaveBeenCalled();
  });

  it("dismiss удаляет одну задачу", async () => {
    const { result } = setup();

    act(() => result.current.enqueue([makeFile()], "parent-1", QKEY));
    await waitFor(() => expect(result.current.tasks[0].status).toBe("done"));
    const id = result.current.tasks[0].id;

    act(() => result.current.dismiss(id));
    expect(result.current.tasks).toHaveLength(0);
  });

  it("dismissAllDone удаляет завершённые и ошибочные задачи", async () => {
    const { result } = setup();

    // Одна успешная.
    act(() => result.current.enqueue([makeFile("ok.png")], "parent-1", QKEY));
    await waitFor(() => expect(result.current.tasks).toHaveLength(1));
    await waitFor(() => expect(result.current.tasks[0].status).toBe("done"));

    // Одна ошибочная (без папки).
    act(() => result.current.enqueue([makeFile("bad.png")], null, QKEY));
    await waitFor(() => expect(result.current.tasks).toHaveLength(2));
    await waitFor(() =>
      expect(result.current.tasks.every((t) => t.status === "done" || t.status === "error")).toBe(
        true,
      ),
    );

    act(() => result.current.dismissAllDone());
    expect(result.current.tasks).toHaveLength(0);
  });

  it("ставит лишние файлы в очередь сверх лимита параллельности", async () => {
    // 6 файлов > MAX_CONCURRENT_UPLOADS (5): все в итоге завершаются.
    const { result } = setup();
    const files = Array.from({ length: 6 }, (_, i) => makeFile(`f${i}.png`));

    act(() => result.current.enqueue(files, "parent-1", QKEY));
    expect(result.current.tasks).toHaveLength(6);

    await waitFor(
      () => expect(result.current.tasks.every((t) => t.status === "done")).toBe(true),
      { timeout: 5000 },
    );
    expect(createMock).toHaveBeenCalledTimes(6);
  });
});
