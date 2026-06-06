import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { NodeListItem } from "@/types/nodes";
import { InfoPanelProvider } from "@/contexts/infoPanel";
import { useInfoPanel } from "@/contexts/infoPanel-context";

function makeItem(id: string): NodeListItem {
  return {
    id,
    owner_id: "owner",
    parent_id: null,
    name: `item-${id}`,
    node_type: "file",
    visibility: "private",
    path: "",
    depth: 0,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    is_deleted: false,
    file_size_bytes: 1,
    file_mime_type: null,
  } as NodeListItem;
}

describe("useInfoPanel", () => {
  it("выбрасывает ошибку вне провайдера", () => {
    expect(() => renderHook(() => useInfoPanel())).toThrow(
      "useInfoPanel должен использоваться внутри InfoPanelProvider",
    );
  });

  it("по умолчанию ничего не выбрано", () => {
    const { result } = renderHook(() => useInfoPanel(), { wrapper: InfoPanelProvider });
    expect(result.current.selectedItem).toBeNull();
  });

  it("открывает и закрывает панель", () => {
    const { result } = renderHook(() => useInfoPanel(), { wrapper: InfoPanelProvider });
    const item = makeItem("1");

    act(() => result.current.openInfo(item));
    expect(result.current.selectedItem).toBe(item);

    act(() => result.current.closeInfo());
    expect(result.current.selectedItem).toBeNull();
  });

  it("заменяет выбранный элемент при повторном открытии", () => {
    const { result } = renderHook(() => useInfoPanel(), { wrapper: InfoPanelProvider });
    const first = makeItem("1");
    const second = makeItem("2");

    act(() => result.current.openInfo(first));
    act(() => result.current.openInfo(second));
    expect(result.current.selectedItem).toBe(second);
  });
});
