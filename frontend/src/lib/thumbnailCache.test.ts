import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THUMBNAIL_URL_TTL_MS } from "@/lib/constants";
import { getThumbnailCache, setThumbnailCache } from "./thumbnailCache";

const PREFIX = "lc:thumb:";

describe("thumbnailCache", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    sessionStorage.clear();
  });

  describe("getThumbnailCache", () => {
    it("возвращает undefined, если значения нет в storage", () => {
      expect(getThumbnailCache("missing")).toBeUndefined();
    });

    it("возвращает сохранённый URL, если значение свежее", () => {
      setThumbnailCache("id1", "https://cdn/thumb.png");
      expect(getThumbnailCache("id1")).toBe("https://cdn/thumb.png");
    });

    it("возвращает null для маркера отсутствующего thumbnail", () => {
      setThumbnailCache("id2", null);
      expect(getThumbnailCache("id2")).toBeNull();
    });

    it("возвращает undefined и удаляет запись старого формата без timestamp", () => {
      sessionStorage.setItem(PREFIX + "old", "https://cdn/no-ts.png");
      expect(getThumbnailCache("old")).toBeUndefined();
      expect(sessionStorage.getItem(PREFIX + "old")).toBeNull();
    });

    it("возвращает undefined и удаляет запись с нечисловым timestamp", () => {
      sessionStorage.setItem(PREFIX + "nan", "abc|https://cdn/x.png");
      expect(getThumbnailCache("nan")).toBeUndefined();
      expect(sessionStorage.getItem(PREFIX + "nan")).toBeNull();
    });

    it("возвращает undefined и удаляет запись с истёкшим TTL", () => {
      vi.useFakeTimers();
      vi.setSystemTime(0);
      setThumbnailCache("expired", "https://cdn/x.png");
      vi.setSystemTime(THUMBNAIL_URL_TTL_MS + 1);
      expect(getThumbnailCache("expired")).toBeUndefined();
      expect(sessionStorage.getItem(PREFIX + "expired")).toBeNull();
    });

    it("возвращает URL, если TTL ещё не истёк ровно на границе", () => {
      vi.useFakeTimers();
      vi.setSystemTime(0);
      setThumbnailCache("edge", "https://cdn/edge.png");
      vi.setSystemTime(THUMBNAIL_URL_TTL_MS);
      expect(getThumbnailCache("edge")).toBe("https://cdn/edge.png");
    });

    it("возвращает undefined, если storage бросает исключение", () => {
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("blocked");
      });
      expect(getThumbnailCache("any")).toBeUndefined();
    });
  });

  describe("setThumbnailCache", () => {
    it("сохраняет значение с timestamp и URL", () => {
      vi.useFakeTimers();
      vi.setSystemTime(12345);
      setThumbnailCache("s1", "https://cdn/s.png");
      expect(sessionStorage.getItem(PREFIX + "s1")).toBe("12345|https://cdn/s.png");
    });

    it("сохраняет пустой URL для null-маркера", () => {
      vi.useFakeTimers();
      vi.setSystemTime(7);
      setThumbnailCache("s2", null);
      expect(sessionStorage.getItem(PREFIX + "s2")).toBe("7|");
    });

    it("деградирует тихо, если storage бросает исключение", () => {
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("quota");
      });
      expect(() => setThumbnailCache("s3", "https://cdn/s.png")).not.toThrow();
    });
  });

  it("round-trip через set/get сохраняет значение", () => {
    setThumbnailCache("rt", "https://cdn/rt.png");
    expect(getThumbnailCache("rt")).toBe("https://cdn/rt.png");
  });
});
