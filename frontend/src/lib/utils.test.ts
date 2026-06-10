import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("объединяет простые строки классов", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("отбрасывает falsy-значения", () => {
    expect(cn("a", false, null, undefined, "", "b")).toBe("a b");
  });

  it("разворачивает условные объекты clsx", () => {
    expect(cn("base", { active: true, hidden: false })).toBe("base active");
  });

  it("разворачивает массивы классов", () => {
    expect(cn(["a", "b"], ["c"])).toBe("a b c");
  });

  it("разрешает конфликты Tailwind через tailwind-merge", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
  });

  it("сохраняет неконфликтующие Tailwind-классы", () => {
    expect(cn("px-2", "py-4")).toBe("px-2 py-4");
  });

  it("возвращает пустую строку без аргументов", () => {
    expect(cn()).toBe("");
  });
});
