import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const enqueue = vi.fn();
vi.mock("@/contexts/upload-context", () => ({ useUpload: () => ({ enqueue }) }));

const invalidateQueries = vi.fn();
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries }),
}));

vi.mock("@/api/folders", () => ({ foldersApi: { create: vi.fn() } }));
vi.mock("@/lib/errors", () => ({ friendlyError: vi.fn(() => "friendly error") }));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  }),
}));

import { foldersApi } from "@/api/folders";
import { friendlyError } from "@/lib/errors";
import { toast } from "sonner";
import { useFolderUpload } from "@/hooks/useFolderUpload";

const create = vi.mocked(foldersApi.create);

/** Создаёт File с заданным webkitRelativePath. */
function makeFile(relPath: string, size = 10): File {
  const f = new File([new Uint8Array(size)], relPath.split("/").pop() ?? "f");
  Object.defineProperty(f, "webkitRelativePath", { value: relPath });
  return f;
}

const QK = ["nodes", "root"];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(toast.loading).mockReturnValue("t1" as never);
  // Каждый созданный folder получает уникальный node_id по имени.
  let counter = 0;
  create.mockImplementation(async ({ name }) => ({ node_id: `nid-${name}-${counter++}` }) as never);
});

describe("useFolderUpload", () => {
  it("does nothing when no valid files (empty / no relative path)", async () => {
    const { result } = renderHook(() => useFolderUpload());
    const noPath = new File([new Uint8Array(5)], "x.txt");
    const empty = makeFile("proj/empty.txt", 0);
    await act(async () => {
      await result.current.uploadFolder([noPath, empty], "parent", QK);
    });
    expect(create).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("creates nested directory structure top-down and enqueues grouped files", async () => {
    const files = [
      makeFile("proj/src/utils/helper.ts"),
      makeFile("proj/src/index.ts"),
      makeFile("proj/readme.md"),
    ];

    const { result } = renderHook(() => useFolderUpload());
    await act(async () => {
      await result.current.uploadFolder(files, "parent", QK);
    });

    // Уникальные dirs: proj, proj/src, proj/src/utils.
    expect(create).toHaveBeenCalledTimes(3);
    const createdNames = create.mock.calls.map((c) => c[0].name);
    // Верхний уровень создаётся раньше вложенных.
    expect(createdNames[0]).toBe("proj");
    expect(createdNames).toEqual(expect.arrayContaining(["proj", "src", "utils"]));

    // proj создаётся с parent_id = "parent".
    const projCall = create.mock.calls.find((c) => c[0].name === "proj")!;
    expect(projCall[0].parent_id).toBe("parent");

    // Файлы группируются по целевым папкам -> три группы (proj, proj/src, proj/src/utils).
    expect(enqueue).toHaveBeenCalledTimes(3);
    // Каждый enqueue получает query key.
    for (const call of enqueue.mock.calls) {
      expect(call[2]).toBe(QK);
    }

    expect(toast.dismiss).toHaveBeenCalledWith("t1");
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: QK });
  });

  it("reports folder creation errors via toast and skips children of failed parent", async () => {
    create.mockReset();
    // "proj" успешно, "proj/src" падает -> helper в proj/src/utils не создаётся.
    create.mockImplementation(async ({ name }) => {
      if (name === "src") throw new Error("conflict");
      return { node_id: `nid-${name}` } as never;
    });

    const files = [makeFile("proj/src/utils/helper.ts")];
    const { result } = renderHook(() => useFolderUpload());
    await act(async () => {
      await result.current.uploadFolder(files, "parent", QK);
    });

    expect(friendlyError).toHaveBeenCalledWith(expect.any(Error), {
      operation: "createFolder",
      name: "src",
    });
    expect(toast.error).toHaveBeenCalledWith("friendly error");

    // utils пропущен, потому что его родитель proj/src не создан.
    const createdNames = create.mock.calls.map((c) => c[0].name);
    expect(createdNames).not.toContain("utils");

    // Файл не попадает ни в одну группу -> enqueue не вызывается.
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("uploads flat-folder files into a single group", async () => {
    const files = [makeFile("docs/a.txt"), makeFile("docs/b.txt")];
    const { result } = renderHook(() => useFolderUpload());
    await act(async () => {
      await result.current.uploadFolder(files, "parent", QK);
    });
    expect(create).toHaveBeenCalledTimes(1);
    expect(enqueue).toHaveBeenCalledTimes(1);
    expect(enqueue.mock.calls[0][1]).toMatch(/^nid-docs/);
    expect((enqueue.mock.calls[0][0] as File[]).length).toBe(2);
  });
});
