import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { FOLDER_COLORS, getFolderColor, setFolderColor } from "@/components/files/folderColors";

const STORAGE_KEY = "folder-colors";

/**
 * jsdom в этом окружении не предоставляет рабочий `window.localStorage`
 * (Node experimental webstorage перекрывает его). Ставим Map-backed стаб.
 */
function installLocalStorage(): Storage {
  const map = new Map<string, string>();
  const stub: Storage = {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    setItem: (k: string, v: string) => {
      map.set(k, String(v));
    },
    removeItem: (k: string) => {
      map.delete(k);
    },
    key: (i: number) => Array.from(map.keys())[i] ?? null,
  };
  Object.defineProperty(window, "localStorage", {
    value: stub,
    configurable: true,
    writable: true,
  });
  return stub;
}

describe("folderColors", () => {
  let store: Storage;

  beforeEach(() => {
    store = installLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("FOLDER_COLORS", () => {
    it("содержит набор цветов с уникальными значениями и непустыми метками", () => {
      expect(FOLDER_COLORS.length).toBeGreaterThan(0);
      const values = FOLDER_COLORS.map((c) => c.value);
      expect(new Set(values).size).toBe(values.length);
      for (const c of FOLDER_COLORS) {
        expect(c.label).toBeTruthy();
        expect(c.value).toMatch(/^#[0-9a-f]{6}$/i);
      }
    });
  });

  describe("getFolderColor", () => {
    it("возвращает null, когда цвет не задан", () => {
      expect(getFolderColor("missing")).toBeNull();
    });

    it("возвращает сохранённый цвет для идентификатора", () => {
      store.setItem(STORAGE_KEY, JSON.stringify({ a: "#eab308" }));
      expect(getFolderColor("a")).toBe("#eab308");
      expect(getFolderColor("b")).toBeNull();
    });

    it("возвращает null при ошибке парсинга JSON", () => {
      store.setItem(STORAGE_KEY, "{not-json");
      expect(getFolderColor("a")).toBeNull();
    });

    it("возвращает null, когда чтение из localStorage бросает исключение", () => {
      vi.spyOn(store, "getItem").mockImplementation(() => {
        throw new Error("denied");
      });
      expect(getFolderColor("a")).toBeNull();
    });
  });

  describe("setFolderColor", () => {
    it("сохраняет цвет папки в localStorage", () => {
      setFolderColor("a", "#3b82f6");
      expect(JSON.parse(store.getItem(STORAGE_KEY)!)).toEqual({ a: "#3b82f6" });
      expect(getFolderColor("a")).toBe("#3b82f6");
    });

    it("обновляет цвет, сохраняя другие записи", () => {
      setFolderColor("a", "#3b82f6");
      setFolderColor("b", "#22c55e");
      setFolderColor("a", "#ef4444");
      expect(JSON.parse(store.getItem(STORAGE_KEY)!)).toEqual({
        a: "#ef4444",
        b: "#22c55e",
      });
    });

    it("удаляет цвет при передаче null", () => {
      setFolderColor("a", "#3b82f6");
      setFolderColor("a", null);
      expect(getFolderColor("a")).toBeNull();
      expect(JSON.parse(store.getItem(STORAGE_KEY)!)).toEqual({});
    });

    it("игнорирует ошибки записи в localStorage", () => {
      vi.spyOn(store, "setItem").mockImplementation(() => {
        throw new Error("quota");
      });
      expect(() => setFolderColor("a", "#3b82f6")).not.toThrow();
    });
  });
});
