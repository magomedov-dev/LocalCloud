import { describe, it, expect } from "vitest";
import { detectPreviewKind } from "./filePreviewKind";

describe("detectPreviewKind", () => {
  describe("по расширению — изображения", () => {
    it.each(["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"])(
      "распознаёт .%s как image",
      (ext) => {
        expect(detectPreviewKind(`photo.${ext}`)).toBe("image");
      },
    );

    it("нечувствительна к регистру расширения", () => {
      expect(detectPreviewKind("PHOTO.JPG")).toBe("image");
      expect(detectPreviewKind("Photo.PnG")).toBe("image");
    });
  });

  describe("по расширению — видео", () => {
    it.each(["mp4", "webm", "ogv", "mov", "mkv"])("распознаёт .%s как video", (ext) => {
      expect(detectPreviewKind(`clip.${ext}`)).toBe("video");
    });
  });

  describe("по расширению — аудио", () => {
    it.each(["mp3", "wav", "ogg", "flac", "aac", "m4a", "opus"])(
      "распознаёт .%s как audio",
      (ext) => {
        expect(detectPreviewKind(`song.${ext}`)).toBe("audio");
      },
    );
  });

  describe("PDF", () => {
    it("распознаёт .pdf по расширению", () => {
      expect(detectPreviewKind("doc.pdf")).toBe("pdf");
    });

    it("распознаёт application/pdf по mime без известного расширения", () => {
      expect(detectPreviewKind("doc.bin", "application/pdf")).toBe("pdf");
    });
  });

  describe("markdown", () => {
    it.each(["md", "mdx", "markdown"])("распознаёт .%s как markdown", (ext) => {
      expect(detectPreviewKind(`readme.${ext}`)).toBe("markdown");
    });

    it("распознаёт markdown по mime", () => {
      expect(detectPreviewKind("readme.unknownext", "text/markdown")).toBe("markdown");
      expect(detectPreviewKind("readme.unknownext", "text/x-markdown")).toBe("markdown");
    });
  });

  describe("текст по расширению", () => {
    it.each([
      "txt",
      "log",
      "csv",
      "json",
      "yaml",
      "yml",
      "html",
      "css",
      "js",
      "ts",
      "tsx",
      "py",
      "go",
      "rs",
      "sh",
      "sql",
      "xml",
    ])("распознаёт .%s как text", (ext) => {
      expect(detectPreviewKind(`file.${ext}`)).toBe("text");
    });

    it("распознаёт файлы без расширения по полному имени (Dockerfile)", () => {
      expect(detectPreviewKind("Dockerfile")).toBe("text");
      expect(detectPreviewKind("Makefile")).toBe("text");
    });

    it("распознаёт dotfiles по части после точки", () => {
      expect(detectPreviewKind(".gitignore")).toBe("text");
      expect(detectPreviewKind(".editorconfig")).toBe("text");
    });
  });

  describe("текст по mime", () => {
    it("распознаёт text/* как text", () => {
      expect(detectPreviewKind("file.unknownext", "text/plain")).toBe("text");
    });

    it("распознаёт application/* текстовые mime как text", () => {
      expect(detectPreviewKind("file.unknownext", "application/json")).toBe("text");
      expect(detectPreviewKind("file.unknownext", "application/xml")).toBe("text");
      expect(detectPreviewKind("file.unknownext", "application/x-sh")).toBe("text");
    });
  });

  describe("mime по умолчанию для бинарных типов", () => {
    it("image/* mime без известного текстового расширения", () => {
      expect(detectPreviewKind("file.unknownext", "image/png")).toBe("image");
    });

    it("video/* mime", () => {
      expect(detectPreviewKind("file.unknownext", "video/mp4")).toBe("video");
    });

    it("audio/* mime", () => {
      expect(detectPreviewKind("file.unknownext", "audio/mpeg")).toBe("audio");
    });
  });

  describe("приоритет известного текстового расширения над mime", () => {
    it(".ts c video/mp2t mime считается текстом, а не видео", () => {
      expect(detectPreviewKind("module.ts", "video/mp2t")).toBe("text");
    });

    it("текстовое расширение игнорирует image-mime", () => {
      // .svg тоже image, но он проверяется отдельным image-блоком после text-guard.
      expect(detectPreviewKind("data.json", "image/png")).toBe("text");
    });
  });

  describe("неизвестные типы", () => {
    it("возвращает null для неизвестного расширения без mime", () => {
      expect(detectPreviewKind("file.unknownext")).toBeNull();
    });

    it("возвращает null для бинарного mime без поддержки", () => {
      expect(detectPreviewKind("file.bin", "application/octet-stream")).toBeNull();
    });

    it("возвращает null для null mime", () => {
      expect(detectPreviewKind("file.bin", null)).toBeNull();
    });

    it("возвращает null для имени без расширения и без mime", () => {
      expect(detectPreviewKind("noextname")).toBeNull();
    });
  });
});
