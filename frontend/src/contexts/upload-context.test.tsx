import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { UploadContext, useUpload, type UploadContextValue } from "./upload-context";

describe("useUpload", () => {
  it("выбрасывает ошибку вне провайдера", () => {
    expect(() => renderHook(() => useUpload())).toThrow(
      "useUpload должен использоваться внутри <UploadProvider>",
    );
  });

  it("возвращает значение контекста внутри провайдера", () => {
    const value: UploadContextValue = {
      tasks: [{ id: "1", filename: "f.png", progress: 0, status: "pending", error: null }],
      enqueue: () => {},
      dismiss: () => {},
      dismissAllDone: () => {},
    };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <UploadContext.Provider value={value}>{children}</UploadContext.Provider>
    );
    const { result } = renderHook(() => useUpload(), { wrapper });
    expect(result.current).toBe(value);
    expect(result.current.tasks).toHaveLength(1);
  });
});
