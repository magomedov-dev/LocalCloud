import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const downloadMock = vi.fn();
vi.mock("@/api/nodes", () => ({
  nodesApi: {
    download: (...args: unknown[]) => downloadMock(...args),
  },
}));

import { downloadBlobFromUrl, downloadNodeFile } from "./download";

describe("downloadBlobFromUrl", () => {
  let clickSpy: ReturnType<typeof vi.spyOn>;
  let appendSpy: ReturnType<typeof vi.spyOn>;
  let removeSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    appendSpy = vi.spyOn(document.body, "appendChild");
    removeSpy = vi.spyOn(document.body, "removeChild");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("создаёт anchor с href и download, кликает и удаляет его", () => {
    downloadBlobFromUrl("https://example.com/file.bin", "file.bin");

    const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
    expect(anchor.tagName).toBe("A");
    expect(anchor.href).toBe("https://example.com/file.bin");
    expect(anchor.getAttribute("download")).toBe("file.bin");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(removeSpy).toHaveBeenCalledWith(anchor);
    expect(document.body.contains(anchor)).toBe(false);
  });

  it("не устанавливает download-атрибут, если filename не передан", () => {
    downloadBlobFromUrl("https://example.com/file.bin");
    const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
    expect(anchor.hasAttribute("download")).toBe(false);
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });
});

describe("downloadNodeFile", () => {
  let clickSpy: ReturnType<typeof vi.spyOn>;
  let appendSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    downloadMock.mockReset();
    clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    appendSpy = vi.spyOn(document.body, "appendChild");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("использует filename из ответа backend, если он есть", async () => {
    downloadMock.mockResolvedValue({
      presigned_url: "https://cdn/p.png",
      filename: "server-name.png",
    });

    await downloadNodeFile("node-1", "fallback.png");

    expect(downloadMock).toHaveBeenCalledWith("node-1");
    const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
    expect(anchor.href).toBe("https://cdn/p.png");
    expect(anchor.getAttribute("download")).toBe("server-name.png");
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("использует fallback filename, если backend его не вернул", async () => {
    downloadMock.mockResolvedValue({ presigned_url: "https://cdn/q.png" });

    await downloadNodeFile("node-2", "fallback.png");

    const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
    expect(anchor.getAttribute("download")).toBe("fallback.png");
  });

  it("пробрасывает ошибку, если download-запрос отклонён", async () => {
    downloadMock.mockRejectedValue(new Error("boom"));
    await expect(downloadNodeFile("node-3", "f.png")).rejects.toThrow("boom");
  });
});
