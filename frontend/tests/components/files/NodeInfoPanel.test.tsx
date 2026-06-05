import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NodeInfoPanel } from "@/components/files/NodeInfoPanel";
import { nodesApi } from "@/api/nodes";
import type { NodeListItem } from "@/types/nodes";

vi.mock("@/api/nodes", () => ({
  nodesApi: { thumbnail: vi.fn() },
}));

let previewsEnabled = true;
vi.mock("@/hooks/useFeatures", () => ({
  useFeatures: () => ({
    previews_enabled: previewsEnabled,
    file_viewer_enabled: true,
    media_playback_enabled: true,
    file_editing_enabled: true,
  }),
}));

const getThumbnailCache = vi.fn<(id: string) => string | null | undefined>();
const setThumbnailCache = vi.fn();
vi.mock("@/lib/thumbnailCache", () => ({
  getThumbnailCache: (id: string) => getThumbnailCache(id),
  setThumbnailCache: (...args: unknown[]) => setThumbnailCache(...args),
}));

const getFolderColor = vi.fn<(id: string) => string | null>(() => null);
vi.mock("@/components/files/folderColors", () => ({
  getFolderColor: (id: string) => getFolderColor(id),
}));

const queryData = new Map<string, unknown>();
vi.mock("@/lib/query-client", () => ({
  queryClient: {
    getQueryData: (key: unknown[]) => queryData.get(JSON.stringify(key)),
    setQueryData: (key: unknown[], value: unknown) => queryData.set(JSON.stringify(key), value),
  },
}));

const mockThumbnail = vi.mocked(nodesApi.thumbnail);

function fileNode(overrides: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: "f1",
    owner_id: "o",
    parent_id: null,
    name: "report.pdf",
    node_type: "file",
    visibility: "private",
    path: "/report.pdf",
    depth: 0,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-02-02T12:00:00Z",
    is_deleted: false,
    file_mime_type: "application/pdf",
    file_size_bytes: 2048,
    ...overrides,
  };
}

function folderNode(overrides: Partial<NodeListItem> = {}): NodeListItem {
  return fileNode({
    id: "d1",
    name: "Папка",
    node_type: "folder",
    path: "/Папка",
    file_mime_type: null,
    file_size_bytes: null,
    ...overrides,
  });
}

describe("NodeInfoPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryData.clear();
    previewsEnabled = true;
    getThumbnailCache.mockReturnValue(undefined);
    getFolderColor.mockReturnValue(null);
    // Дефолт: thumbnail-эндпоинт что-то возвращает (тесты метаданных используют
    // PDF, который теперь тоже запрашивает миниатюру). Тесты про сами превью
    // переопределяют этот мок.
    mockThumbnail.mockResolvedValue({ presigned_url: "https://cdn/default.webp" } as never);
  });

  it("показывает метаданные файла", () => {
    render(<NodeInfoPanel item={fileNode()} onClose={vi.fn()} />);
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("Файл")).toBeInTheDocument();
    expect(screen.getByText("application/pdf")).toBeInTheDocument();
    expect(screen.getByText("Приватный")).toBeInTheDocument();
    expect(screen.getByText("/report.pdf")).toBeInTheDocument();
    // Размер форматируется
    expect(screen.getByText("Размер")).toBeInTheDocument();
  });

  it("показывает метаданные папки и не показывает MIME/размер", () => {
    render(<NodeInfoPanel item={folderNode()} onClose={vi.fn()} />);
    // «Папка» встречается и как имя, и как значение типа
    expect(screen.getAllByText("Папка").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("MIME-тип")).not.toBeInTheDocument();
    expect(screen.queryByText("Размер")).not.toBeInTheDocument();
  });

  it("отображает понятную метку видимости и сырое значение при отсутствии метки", () => {
    render(<NodeInfoPanel item={fileNode({ visibility: "public" })} onClose={vi.fn()} />);
    expect(screen.getByText("Публичный")).toBeInTheDocument();
  });

  it("вызывает onClose по кнопке закрытия и по backdrop", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { container } = render(<NodeInfoPanel item={fileNode()} onClose={onClose} />);
    await user.click(screen.getByRole("button"));
    expect(onClose).toHaveBeenCalledTimes(1);

    const backdrop = container.querySelector('[aria-hidden="true"]')!;
    await user.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("не запрашивает thumbnail для типа без миниатюры (zip)", () => {
    render(
      <NodeInfoPanel
        item={fileNode({ name: "a.zip", file_mime_type: "application/zip" })}
        onClose={vi.fn()}
      />,
    );
    expect(mockThumbnail).not.toHaveBeenCalled();
  });

  it("загружает thumbnail изображения через API и показывает превью", async () => {
    mockThumbnail.mockResolvedValue({ presigned_url: "https://cdn/thumb.png" } as never);
    const img = fileNode({ name: "pic.png", file_mime_type: "image/png" });
    render(<NodeInfoPanel item={img} onClose={vi.fn()} />);

    await waitFor(() => expect(mockThumbnail).toHaveBeenCalledWith("f1"));
    const el = await screen.findByAltText("pic.png");
    expect(el).toHaveAttribute("src", "https://cdn/thumb.png");
    expect(setThumbnailCache).toHaveBeenCalledWith("f1", "https://cdn/thumb.png");
  });

  it("показывает миниатюру для PDF (а не только для изображений)", async () => {
    mockThumbnail.mockResolvedValue({ presigned_url: "https://cdn/book.webp" } as never);
    // По умолчанию fileNode — это PDF; теперь у него тоже есть миниатюра.
    render(<NodeInfoPanel item={fileNode({ name: "book.pdf" })} onClose={vi.fn()} />);

    await waitFor(() => expect(mockThumbnail).toHaveBeenCalledWith("f1"));
    expect(await screen.findByAltText("book.pdf")).toHaveAttribute(
      "src",
      "https://cdn/book.webp",
    );
  });

  it("показывает миниатюру для видео", async () => {
    mockThumbnail.mockResolvedValue({ presigned_url: "https://cdn/clip.webp" } as never);
    render(
      <NodeInfoPanel
        item={fileNode({ name: "clip.mp4", file_mime_type: "video/mp4" })}
        onClose={vi.fn()}
      />,
    );
    await waitFor(() => expect(mockThumbnail).toHaveBeenCalledWith("f1"));
    expect(await screen.findByAltText("clip.mp4")).toBeInTheDocument();
  });

  it("не запрашивает миниатюру и показывает иконку при выключенных превью", () => {
    previewsEnabled = false;
    render(
      <NodeInfoPanel
        item={fileNode({ name: "pic.png", file_mime_type: "image/png" })}
        onClose={vi.fn()}
      />,
    );
    expect(mockThumbnail).not.toHaveBeenCalled();
    expect(screen.queryByAltText("pic.png")).not.toBeInTheDocument();
  });

  it("использует thumbnail из React Query кеша без вызова API", async () => {
    queryData.set(JSON.stringify(["thumbnail", "f1"]), "https://cdn/cached.png");
    const img = fileNode({ name: "pic.png", file_mime_type: "image/png" });
    render(<NodeInfoPanel item={img} onClose={vi.fn()} />);

    expect(await screen.findByAltText("pic.png")).toHaveAttribute("src", "https://cdn/cached.png");
    expect(mockThumbnail).not.toHaveBeenCalled();
  });

  it("использует thumbnail из sessionStorage кеша без вызова API", async () => {
    getThumbnailCache.mockReturnValue("https://cdn/session.png");
    const img = fileNode({ name: "pic.png", file_mime_type: "image/png" });
    render(<NodeInfoPanel item={img} onClose={vi.fn()} />);

    expect(await screen.findByAltText("pic.png")).toHaveAttribute("src", "https://cdn/session.png");
    expect(mockThumbnail).not.toHaveBeenCalled();
  });

  it("показывает иконку при ошибке загрузки thumbnail", async () => {
    mockThumbnail.mockRejectedValue(new Error("404"));
    const img = fileNode({ name: "pic.png", file_mime_type: "image/png" });
    render(<NodeInfoPanel item={img} onClose={vi.fn()} />);

    await waitFor(() => expect(mockThumbnail).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByAltText("pic.png")).not.toBeInTheDocument());
  });

  it("запрашивает цвет папки для папки", () => {
    render(<NodeInfoPanel item={folderNode()} onClose={vi.fn()} />);
    expect(getFolderColor).toHaveBeenCalledWith("d1");
  });
});
