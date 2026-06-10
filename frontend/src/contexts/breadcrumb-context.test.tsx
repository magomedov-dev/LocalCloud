import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { BreadcrumbProvider } from "./breadcrumb";
import { useBreadcrumb } from "./breadcrumb-context";

describe("useBreadcrumb", () => {
  it("выбрасывает ошибку вне провайдера", () => {
    expect(() => renderHook(() => useBreadcrumb())).toThrow(
      "useBreadcrumb должен использоваться внутри <BreadcrumbProvider>",
    );
  });

  it("начинается с пустого списка крошек", () => {
    const { result } = renderHook(() => useBreadcrumb(), { wrapper: BreadcrumbProvider });
    expect(result.current.crumbs).toEqual([]);
  });

  it("обновляет крошки через setCrumbs", () => {
    const { result } = renderHook(() => useBreadcrumb(), { wrapper: BreadcrumbProvider });
    const crumbs = [
      { label: "Главная", href: "/" },
      { label: "Папка" },
    ];
    act(() => result.current.setCrumbs(crumbs));
    expect(result.current.crumbs).toEqual(crumbs);
  });
});
