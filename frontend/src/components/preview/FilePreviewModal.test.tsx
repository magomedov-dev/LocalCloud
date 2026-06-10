import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("@/api/nodes", () => ({
  nodesApi: {
    download: vi.fn(),
    thumbnail: vi.fn(),
    softDelete: vi.fn(),
    streamUrl: vi.fn((id: string) => `/api/v1/nodes/${id}/stream`),
  },
}));

vi.mock("@/api/uploads", () => ({
  uploadsApi: {
    create: vi.fn(),
    getPresignedParts: vi.fn(),
    completePart: vi.fn(),
    complete: vi.fn(),
  },
}));

vi.mock("@/lib/download", () => ({
  downloadBlobFromUrl: vi.fn(),
}));

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { nodesApi } from "@/api/nodes";
import { uploadsApi } from "@/api/uploads";
import { downloadBlobFromUrl } from "@/lib/download";
import type { NodeListItem } from "@/types/nodes";
import type { FileDownloadResponse } from "@/types/files";
import { FilePreviewModal } from "./FilePreviewModal";

const download = vi.mocked(nodesApi.download);
const thumbnail = vi.mocked(nodesApi.thumbnail);
const softDelete = vi.mocked(nodesApi.softDelete);
const uploadCreate = vi.mocked(uploadsApi.create);
const getPresignedParts = vi.mocked(uploadsApi.getPresignedParts);
const completePart = vi.mocked(uploadsApi.completePart);
const complete = vi.mocked(uploadsApi.complete);
const downloadBlob = vi.mocked(downloadBlobFromUrl);

// ── Fixtures ─────────────────────────────────────────────────────────────────

function makeItem(over: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: "node-1",
    owner_id: "owner-1",
    parent_id: "parent-1",
    name: "file.txt",
    node_type: "file",
    visibility: "private",
    path: "/file.txt",
    depth: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    is_deleted: false,
    file_size_bytes: 100,
    file_mime_type: "text/plain",
    ...over,
  };
}

function makeDownloadResp(over: Partial<FileDownloadResponse> = {}): FileDownloadResponse {
  return {
    presigned_url: "https://storage.example/presigned",
    expires_at: "2099-01-01T00:00:00Z",
    method: "GET",
    headers: {},
    ...over,
  };
}

function renderModal(props: Partial<Parameters<typeof FilePreviewModal>[0]> = {}) {
  const onClose = props.onClose ?? vi.fn();
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  const utils = render(
    <QueryClientProvider client={qc}>
      <FilePreviewModal
        item={props.item ?? makeItem()}
        mimeType={props.mimeType}
        open={props.open ?? true}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onClose, qc };
}

// global mocks for blob / object url
const origCreateObjectURL = URL.createObjectURL;
const origRevokeObjectURL = URL.revokeObjectURL;

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  // default resolved download
  download.mockResolvedValue(makeDownloadResp());
  thumbnail.mockResolvedValue(makeDownloadResp({ presigned_url: "https://poster.example/p" }));
});

afterEach(() => {
  URL.createObjectURL = origCreateObjectURL;
  URL.revokeObjectURL = origRevokeObjectURL;
});

// helper to stub globalThis.fetch per test
function stubFetch(impl: (url: string) => Promise<Partial<Response>> | Partial<Response>) {
  globalThis.fetch = vi.fn((url: unknown) =>
    Promise.resolve(impl(String(url))),
  ) as unknown as typeof fetch;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("FilePreviewModal — kind detection / null render", () => {
  it("renders nothing when kind is unknown (e.g. .bin)", () => {
    renderModal({
      item: makeItem({ name: "data.bin", file_mime_type: "application/octet-stream" }),
    });
    // Dialog content not present
    expect(document.querySelector("[role='dialog']")).toBeNull();
    expect(screen.queryByText("data.bin")).toBeNull();
  });

  it("does not load anything when open=false", () => {
    renderModal({ open: false, item: makeItem({ name: "a.png", file_mime_type: "image/png" }) });
    expect(download).not.toHaveBeenCalled();
  });
});

describe("FilePreviewModal — image preview", () => {
  it("loads and renders the image with presigned src", async () => {
    renderModal({
      item: makeItem({ name: "pic.png", file_mime_type: "image/png" }),
    });
    await waitFor(() => expect(download).toHaveBeenCalledWith("node-1", false));
    const img = await waitFor(() => {
      const el = document.querySelector("img");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(img.getAttribute("src")).toBe("https://storage.example/presigned");
    // image kind also loads a poster thumbnail? No — image is excluded.
    expect(thumbnail).not.toHaveBeenCalled();
  });

  it("zoom in/out and reset buttons update the percentage", async () => {
    renderModal({
      item: makeItem({ name: "pic.png", file_mime_type: "image/png" }),
    });
    await waitFor(() => expect(document.querySelector("img")).not.toBeNull());
    expect(screen.getByText("100%")).toBeInTheDocument();
    const buttons = document.querySelectorAll("button");
    // last 3 buttons in image viewer overlay are minus, reset(%), plus
    const plus = Array.from(buttons).find((b) => b.querySelector(".lucide-plus"));
    const minus = Array.from(buttons).find((b) => b.querySelector(".lucide-minus"));
    if (plus) fireEvent.click(plus);
    await waitFor(() => expect(screen.getByText("125%")).toBeInTheDocument());
    if (minus) fireEvent.click(minus);
    await waitFor(() => expect(screen.getByText("100%")).toBeInTheDocument());
    // reset button (showing percentage text)
    fireEvent.click(screen.getByText("100%"));
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("wheel zoom and drag panning when zoomed", async () => {
    renderModal({
      item: makeItem({ name: "pic.png", file_mime_type: "image/png" }),
    });
    await waitFor(() => expect(document.querySelector("img")).not.toBeNull());
    const viewer = document.querySelector(".select-none") as HTMLElement;
    // zoom in via wheel
    fireEvent.wheel(viewer, { deltaY: -100 });
    await waitFor(() => expect(screen.queryByText("100%")).toBeNull());
    // drag (zoom > 1 now)
    fireEvent.mouseDown(viewer, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(viewer, { clientX: 30, clientY: 40 });
    fireEvent.mouseUp(viewer);
    // wheel zoom out below 1 to reset pos
    fireEvent.wheel(viewer, { deltaY: 100 });
    fireEvent.wheel(viewer, { deltaY: 100 });
    fireEvent.wheel(viewer, { deltaY: 100 });
    // mouseDown when not zoomed should early-return (no drag)
    fireEvent.mouseDown(viewer, { clientX: 0, clientY: 0 });
    fireEvent.mouseLeave(viewer);
    expect(viewer).toBeInTheDocument();
  });
});

describe("FilePreviewModal — error and loading states", () => {
  it("shows spinner while loading then error message on download failure", async () => {
    download.mockRejectedValueOnce(new Error("boom"));
    renderModal({ item: makeItem({ name: "pic.png", file_mime_type: "image/png" }) });
    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
  });

  it("falls back to default error message when error has no message", async () => {
    download.mockRejectedValueOnce({});
    renderModal({ item: makeItem({ name: "pic.png", file_mime_type: "image/png" }) });
    await waitFor(() =>
      expect(screen.getByText("Не удалось загрузить файл")).toBeInTheDocument(),
    );
  });
});

describe("FilePreviewModal — pdf preview", () => {
  it("creates a blob url and renders an iframe", async () => {
    stubFetch(() => ({ ok: true, blob: () => Promise.resolve(new Blob(["%PDF"])) }));
    renderModal({
      item: makeItem({ name: "doc.pdf", file_mime_type: "application/pdf" }),
    });
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
    const iframe = await waitFor(() => {
      const el = document.querySelector("iframe");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(iframe.getAttribute("src")).toBe("blob:mock-url");
    // before load, spinner text present
    expect(screen.getByText("Загрузка PDF…")).toBeInTheDocument();
    // simulate iframe load
    fireEvent.load(iframe);
    await waitFor(() => expect(screen.queryByText("Загрузка PDF…")).toBeNull());
  });

  it("falls back to presigned url when fetch is not ok", async () => {
    stubFetch(() => ({ ok: false, status: 500, blob: () => Promise.resolve(new Blob()) }));
    renderModal({
      item: makeItem({ name: "doc.pdf", file_mime_type: "application/pdf" }),
    });
    const iframe = await waitFor(() => {
      const el = document.querySelector("iframe");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(iframe.getAttribute("src")).toBe("https://storage.example/presigned");
  });

  it("falls back to presigned url when blob fetch rejects", async () => {
    // fetch itself rejects -> caught -> pdfBlobUrl set to presigned url
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("network"))) as unknown as typeof fetch;
    renderModal({
      item: makeItem({ name: "doc.pdf", file_mime_type: "application/pdf" }),
    });
    const iframe = await waitFor(() => {
      const el = document.querySelector("iframe");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(iframe.getAttribute("src")).toBe("https://storage.example/presigned");
  });
});

describe("FilePreviewModal — audio preview", () => {
  it("renders audio element and loads poster thumbnail", async () => {
    stubFetch(() => ({ ok: true }));
    renderModal({
      item: makeItem({ name: "song.mp3", file_mime_type: "audio/mpeg" }),
    });
    await waitFor(() => expect(thumbnail).toHaveBeenCalledWith("node-1"));
    const audio = await waitFor(() => {
      const el = document.querySelector("audio");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(audio.getAttribute("src")).toBe("https://storage.example/presigned");
  });

  it("audio controls: play/pause, seek, volume, mute", async () => {
    renderModal({
      item: makeItem({ name: "song.mp3", file_mime_type: "audio/mpeg" }),
    });
    const audio = (await waitFor(() => {
      const el = document.querySelector("audio");
      expect(el).not.toBeNull();
      return el!;
    })) as HTMLAudioElement;

    // stub media methods (jsdom doesn't implement)
    audio.play = vi.fn(() => Promise.resolve());
    audio.pause = vi.fn();

    // metadata + timeupdate
    Object.defineProperty(audio, "duration", { value: 120, configurable: true });
    fireEvent.loadedMetadata(audio);
    Object.defineProperty(audio, "currentTime", { value: 30, writable: true, configurable: true });
    fireEvent.timeUpdate(audio);
    await waitFor(() => expect(screen.getByText("0:30")).toBeInTheDocument());

    // play
    const playBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.querySelector(".lucide-play"),
    )!;
    fireEvent.click(playBtn);
    await waitFor(() => expect(audio.play).toHaveBeenCalled());

    // pause (now playing -> pause icon button)
    const pauseBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.querySelector(".lucide-pause"),
    )!;
    fireEvent.click(pauseBtn);
    expect(audio.pause).toHaveBeenCalled();

    // seek +10 / -10
    const seekFwd = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("+10"),
    )!;
    const seekBack = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("−10"),
    )!;
    fireEvent.click(seekFwd);
    fireEvent.click(seekBack);

    // volume + mute via range inputs
    const ranges = document.querySelectorAll("input[type='range']");
    // seek range (first), volume range (second)
    fireEvent.change(ranges[0], { target: { value: "60" } });
    fireEvent.change(ranges[1], { target: { value: "0" } }); // sets muted
    fireEvent.change(ranges[1], { target: { value: "0.5" } });

    // mute toggle button
    const muteBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.querySelector(".lucide-volume-2") || b.querySelector(".lucide-volume-x"),
    )!;
    fireEvent.click(muteBtn);
  });
});

describe("FilePreviewModal — video preview", () => {
  it("renders video with stream url and poster", async () => {
    stubFetch(() => ({ ok: true }));
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    const video = await waitFor(() => {
      const el = document.querySelector("video");
      expect(el).not.toBeNull();
      return el!;
    });
    expect(video.getAttribute("src")).toBe("/api/v1/nodes/node-1/stream");
    await waitFor(() => expect(thumbnail).toHaveBeenCalled());
    // download should NOT be called for video
    expect(download).not.toHaveBeenCalled();
  });

  it("poster fallback to null when thumbnail fails", async () => {
    thumbnail.mockRejectedValueOnce(new Error("no thumb"));
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    await waitFor(() => expect(document.querySelector("video")).not.toBeNull());
    await waitFor(() => expect(thumbnail).toHaveBeenCalled());
  });

  it("video controls: play/pause/seek/volume/mute/fullscreen + error states", async () => {
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    const video = (await waitFor(() => {
      const el = document.querySelector("video");
      expect(el).not.toBeNull();
      return el!;
    })) as HTMLVideoElement;

    video.play = vi.fn(() => Promise.resolve());
    video.pause = vi.fn();

    Object.defineProperty(video, "duration", { value: 200, configurable: true });
    fireEvent.loadedMetadata(video);

    // click the video area to toggle play
    const videoArea = video.parentElement as HTMLElement;
    fireEvent.click(videoArea);
    await waitFor(() => expect(video.play).toHaveBeenCalled());

    // simulate play event -> playing=true
    fireEvent.play(video);
    Object.defineProperty(video, "currentTime", { value: 50, writable: true, configurable: true });
    fireEvent.timeUpdate(video);
    await waitFor(() => expect(screen.getAllByText("0:50").length).toBeGreaterThan(0));

    // pause via clicking area again (playing) -> pause()
    fireEvent.click(videoArea);
    expect(video.pause).toHaveBeenCalled();
    fireEvent.pause(video);
    fireEvent.ended(video);

    // seek + volume + mute from card controls
    const seekFwd = Array.from(document.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("+10"),
    )!;
    fireEvent.click(seekFwd);
    const ranges = document.querySelectorAll("input[type='range']");
    fireEvent.change(ranges[0], { target: { value: "90" } });
    fireEvent.change(ranges[1], { target: { value: "0" } });
    const muteBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.querySelector(".lucide-volume-x") || b.querySelector(".lucide-volume-2"),
    )!;
    fireEvent.click(muteBtn);

    // fullscreen toggle (requestFullscreen / exitFullscreen stubbed)
    const reqFs = vi.fn();
    const exitFs = vi.fn();
    HTMLElement.prototype.requestFullscreen = reqFs;
    Object.defineProperty(document, "exitFullscreen", { value: exitFs, configurable: true });
    const fsBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.querySelector(".lucide-maximize-2"),
    )!;
    fireEvent.click(fsBtn);
    expect(reqFs).toHaveBeenCalled();

    // codec error
    Object.defineProperty(video, "error", {
      value: { code: 4, message: "DEMUXER_ERROR_NO_SUPPORTED_STREAMS" },
      configurable: true,
    });
    fireEvent.error(video);
    await waitFor(() =>
      expect(
        screen.getByText(/Видеокодек не поддерживается/),
      ).toBeInTheDocument(),
    );
  });

  it("generic video error message for non-codec errors", async () => {
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    const video = (await waitFor(() => {
      const el = document.querySelector("video");
      expect(el).not.toBeNull();
      return el!;
    })) as HTMLVideoElement;
    Object.defineProperty(video, "error", {
      value: { code: 2, message: "network" },
      configurable: true,
    });
    fireEvent.error(video);
    await waitFor(() =>
      expect(screen.getByText("Не удалось воспроизвести видео.")).toBeInTheDocument(),
    );
  });

  it("toggleFullscreen calls exitFullscreen when already fullscreen", async () => {
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    const video = await waitFor(() => {
      const el = document.querySelector("video");
      expect(el).not.toBeNull();
      return el!;
    });
    const exitFs = vi.fn();
    Object.defineProperty(document, "fullscreenElement", {
      value: video.parentElement,
      configurable: true,
    });
    Object.defineProperty(document, "exitFullscreen", { value: exitFs, configurable: true });
    const fsBtn = Array.from(document.querySelectorAll("button")).find(
      (b) => b.querySelector(".lucide-maximize-2"),
    )!;
    fireEvent.click(fsBtn);
    expect(exitFs).toHaveBeenCalled();
    // reset
    Object.defineProperty(document, "fullscreenElement", { value: null, configurable: true });
  });

  it("enters fullscreen overlay UI via fullscreenchange event", async () => {
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    const video = await waitFor(() => {
      const el = document.querySelector("video");
      expect(el).not.toBeNull();
      return el!;
    });
    Object.defineProperty(document, "fullscreenElement", {
      value: video.parentElement,
      configurable: true,
    });
    fireEvent(document, new Event("fullscreenchange"));
    // overlay fullscreen controls render minimize button now
    await waitFor(() =>
      expect(document.querySelector(".lucide-minimize-2")).not.toBeNull(),
    );
    // interact with fullscreen overlay controls
    const fsContainer = video.parentElement!.parentElement as HTMLElement;
    fireEvent.mouseMove(fsContainer);
    fireEvent.mouseLeave(fsContainer);
    // fullscreen seek range exists
    const ranges = document.querySelectorAll("input[type='range']");
    fireEvent.change(ranges[0], { target: { value: "10" } });
    // reset
    Object.defineProperty(document, "fullscreenElement", { value: null, configurable: true });
    fireEvent(document, new Event("fullscreenchange"));
  });
});

describe("FilePreviewModal — text / code preview", () => {
  it("loads and displays plain text with line numbers", async () => {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("line1\nline2\nline3") }));
    renderModal({ item: makeItem({ name: "notes.txt", file_mime_type: "text/plain" }) });
    await waitFor(() => expect(screen.getByText("line1")).toBeInTheDocument());
    expect(screen.getByText("line2")).toBeInTheDocument();
    // line numbers present
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders code file (.ts) as text", async () => {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("const x = 1;") }));
    renderModal({ item: makeItem({ name: "code.ts", file_mime_type: "video/mp2t" }) });
    await waitFor(() => expect(screen.getByText("const x = 1;")).toBeInTheDocument());
  });
});

describe("FilePreviewModal — markdown preview", () => {
  it("renders markdown headings and content", async () => {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("# Hello\n\nSome **text** here") }));
    renderModal({ item: makeItem({ name: "readme.md", file_mime_type: "text/markdown" }) });
    await waitFor(() => expect(screen.getByText("Hello")).toBeInTheDocument());
    expect(screen.getByText("text")).toBeInTheDocument();
  });

  it("renders the full set of markdown custom renderers", async () => {
    const md = [
      "# H1",
      "## H2",
      "### H3",
      "#### H4",
      "",
      "Paragraph text with `inline code` and a [link](https://example.com).",
      "",
      "- ul item one",
      "- ul item two",
      "",
      "1. ol item one",
      "2. ol item two",
      "",
      "> a blockquote",
      "",
      "```js",
      "const block = 1;",
      "```",
      "",
      "---",
      "",
      "| Col A | Col B |",
      "| ----- | ----- |",
      "| a1    | b1    |",
    ].join("\n");
    stubFetch(() => ({ ok: true, text: () => Promise.resolve(md) }));
    renderModal({ item: makeItem({ name: "rich.md", file_mime_type: "text/markdown" }) });

    await waitFor(() => expect(screen.getByText("H1")).toBeInTheDocument());
    expect(screen.getByText("H2")).toBeInTheDocument();
    expect(screen.getByText("H3")).toBeInTheDocument();
    expect(screen.getByText("H4")).toBeInTheDocument();
    expect(screen.getByText("inline code")).toBeInTheDocument();
    expect(screen.getByText("ul item one")).toBeInTheDocument();
    expect(screen.getByText("ol item one")).toBeInTheDocument();
    expect(screen.getByText("a blockquote")).toBeInTheDocument();
    expect(screen.getByText("const block = 1;")).toBeInTheDocument();
    // table renderers
    expect(screen.getByText("Col A")).toBeInTheDocument();
    expect(screen.getByText("a1")).toBeInTheDocument();
    // link renderer
    const link = screen.getByText("link").closest("a");
    expect(link?.getAttribute("href")).toBe("https://example.com");
    // hr renderer
    expect(document.querySelector("hr")).not.toBeNull();
  });
});

describe("FilePreviewModal — text editing & save", () => {
  async function openEditableText(name = "notes.txt") {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("hello\nworld") }));
    const utils = renderModal({ item: makeItem({ name }) });
    await waitFor(() => expect(screen.getByText("hello")).toBeInTheDocument());
    return utils;
  }

  it("enters edit mode and shows the contenteditable editor", async () => {
    await openEditableText();
    const editBtn = screen.getByTitle("Редактировать");
    fireEvent.click(editBtn);
    await waitFor(() =>
      expect(document.querySelector("[contenteditable='true']")).not.toBeNull(),
    );
    expect(screen.getByText("Сохранить")).toBeInTheDocument();
  });

  it("cancel exits edit mode", async () => {
    await openEditableText();
    fireEvent.click(screen.getByTitle("Редактировать"));
    await waitFor(() =>
      expect(document.querySelector("[contenteditable='true']")).not.toBeNull(),
    );
    fireEvent.click(screen.getByText("Отмена"));
    await waitFor(() =>
      expect(document.querySelector("[contenteditable='true']")).toBeNull(),
    );
  });

  it("editor onInput, onPaste, and Tab keyDown handlers", async () => {
    await openEditableText();
    fireEvent.click(screen.getByTitle("Редактировать"));
    const editor = (await waitFor(() => {
      const el = document.querySelector("[contenteditable='true']") as HTMLElement;
      expect(el).not.toBeNull();
      return el;
    })) as HTMLElement;
    document.execCommand = vi.fn(() => true);
    editor.innerText = "new content\nmore";
    fireEvent.input(editor);
    fireEvent.paste(editor, {
      clipboardData: { getData: () => "pasted" },
    });
    fireEvent.keyDown(editor, { key: "Tab" });
    expect(document.execCommand).toHaveBeenCalledWith("insertText", false, "  ");
    // non-tab key does nothing special
    fireEvent.keyDown(editor, { key: "a" });
  });

  it("save: full happy path uploads new version and closes", async () => {
    const { onClose, qc } = await openEditableText();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

    softDelete.mockResolvedValue({});
    uploadCreate.mockResolvedValue({ id: "sess-1" } as never);
    getPresignedParts.mockResolvedValue({
      parts: [{ part_number: 1, url: "https://put.example/part1", headers: { "x-amz": "v", "Content-Length": "5" } }],
    } as never);
    completePart.mockResolvedValue({});
    complete.mockResolvedValue({} as never);

    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        headers: { get: (k: string) => (k.toLowerCase() === "etag" ? '"abc"' : null) },
      }),
    ) as unknown as typeof fetch;

    fireEvent.click(screen.getByTitle("Редактировать"));
    await waitFor(() => expect(screen.getByText("Сохранить")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Сохранить"));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(softDelete).toHaveBeenCalledWith("node-1");
    expect(uploadCreate).toHaveBeenCalled();
    expect(completePart).toHaveBeenCalledWith("sess-1", 1, expect.objectContaining({ etag: "abc" }));
    expect(complete).toHaveBeenCalled();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["nodes"] });
  });

  it("save error: PUT not ok surfaces the error", async () => {
    await openEditableText();
    softDelete.mockResolvedValue({});
    uploadCreate.mockResolvedValue({ id: "sess-1" } as never);
    getPresignedParts.mockResolvedValue({
      parts: [{ part_number: 1, url: "https://put.example/p", headers: {} }],
    } as never);
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({ ok: false, status: 403, headers: { get: () => null } }),
    ) as unknown as typeof fetch;

    fireEvent.click(screen.getByTitle("Редактировать"));
    await waitFor(() => expect(screen.getByText("Сохранить")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => expect(screen.getByText(/Ошибка загрузки: 403/)).toBeInTheDocument());
  });

  it("save error: non-Error rejection shows fallback message", async () => {
    await openEditableText();
    softDelete.mockRejectedValue("string failure");
    fireEvent.click(screen.getByTitle("Редактировать"));
    await waitFor(() => expect(screen.getByText("Сохранить")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() =>
      expect(screen.getByText("Не удалось сохранить файл.")).toBeInTheDocument(),
    );
  });

  it("save blocked when file is in root (no parent_id)", async () => {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("content") }));
    renderModal({
      item: makeItem({ name: "notes.txt", parent_id: null }),
    });
    await waitFor(() => expect(screen.getByText("content")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("Редактировать"));
    await waitFor(() =>
      expect(document.querySelector("[contenteditable='true']")).not.toBeNull(),
    );
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() =>
      expect(screen.getByText("Невозможно сохранить файл в корне.")).toBeInTheDocument(),
    );
    expect(softDelete).not.toHaveBeenCalled();
  });

  it("save blocked when content is empty", async () => {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("content") }));
    renderModal({ item: makeItem({ name: "notes.txt" }) });
    await waitFor(() => expect(screen.getByText("content")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("Редактировать"));
    const editor = (await waitFor(() => {
      const el = document.querySelector("[contenteditable='true']") as HTMLElement;
      expect(el).not.toBeNull();
      return el;
    })) as HTMLElement;
    editor.innerText = "";
    fireEvent.input(editor);
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() =>
      expect(screen.getByText("Файл не может быть пустым.")).toBeInTheDocument(),
    );
    expect(softDelete).not.toHaveBeenCalled();
  });

  it("markdown is saved with text/markdown mime type", async () => {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("# md") }));
    const { onClose } = renderModal({
      item: makeItem({ name: "doc.md", file_mime_type: "text/markdown" }),
    });
    await waitFor(() => expect(screen.getByText("md")).toBeInTheDocument());
    softDelete.mockResolvedValue({});
    uploadCreate.mockResolvedValue({ id: "s" } as never);
    getPresignedParts.mockResolvedValue({
      parts: [{ part_number: 1, url: "u", headers: {} }],
    } as never);
    completePart.mockResolvedValue({});
    complete.mockResolvedValue({} as never);
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, headers: { get: () => '"e"' } }),
    ) as unknown as typeof fetch;

    fireEvent.click(screen.getByTitle("Редактировать"));
    await waitFor(() => expect(screen.getByText("Сохранить")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(uploadCreate).toHaveBeenCalledWith(
      expect.objectContaining({ mime_type: "text/markdown" }),
    );
  });
});

describe("FilePreviewModal — toolbar actions", () => {
  it("download uses existing presigned url", async () => {
    renderModal({
      item: makeItem({ name: "pic.png", file_mime_type: "image/png" }),
    });
    await waitFor(() => expect(document.querySelector("img")).not.toBeNull());
    fireEvent.click(screen.getByTitle("Скачать"));
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith("https://storage.example/presigned", "pic.png"),
    );
  });

  it("download fetches a fresh url when none is loaded (video kind)", async () => {
    download.mockResolvedValue(makeDownloadResp({ presigned_url: "https://fresh.example/u" }));
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    await waitFor(() => expect(document.querySelector("video")).not.toBeNull());
    download.mockClear();
    fireEvent.click(screen.getByTitle("Скачать"));
    await waitFor(() => expect(download).toHaveBeenCalledWith("node-1", true));
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith("https://fresh.example/u", "clip.mp4"),
    );
  });

  it("download silently aborts when fresh url request fails", async () => {
    renderModal({
      item: makeItem({ name: "clip.mp4", file_mime_type: "video/mp4" }),
    });
    await waitFor(() => expect(document.querySelector("video")).not.toBeNull());
    download.mockClear();
    download.mockRejectedValueOnce(new Error("nope"));
    fireEvent.click(screen.getByTitle("Скачать"));
    await waitFor(() => expect(download).toHaveBeenCalledWith("node-1", true));
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("close button calls onClose", async () => {
    const { onClose } = renderModal({
      item: makeItem({ name: "pic.png", file_mime_type: "image/png" }),
    });
    await waitFor(() => expect(document.querySelector("img")).not.toBeNull());
    fireEvent.click(screen.getByTitle("Закрыть"));
    expect(onClose).toHaveBeenCalled();
  });

  it("Escape key closes via radix onOpenChange", async () => {
    stubFetch(() => ({ ok: true, text: () => Promise.resolve("x") }));
    const { onClose } = renderModal({ item: makeItem({ name: "notes.txt" }) });
    await waitFor(() => expect(screen.getByText("x")).toBeInTheDocument());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("FilePreviewModal — formatTime edge via SeekRow", () => {
  it("shows --:-- placeholder for invalid duration", async () => {
    renderModal({
      item: makeItem({ name: "song.mp3", file_mime_type: "audio/mpeg" }),
    });
    await waitFor(() => expect(document.querySelector("audio")).not.toBeNull());
    // initial duration is 0 -> formatTime(0) = "0:00"; set NaN to hit placeholder
    const audio = document.querySelector("audio") as HTMLAudioElement;
    Object.defineProperty(audio, "duration", { value: NaN, configurable: true });
    fireEvent.loadedMetadata(audio);
    await waitFor(() => expect(screen.getByText("--:--")).toBeInTheDocument());
  });
});
