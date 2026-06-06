import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { AuthContext, useAuth, type AuthContextValue } from "@/contexts/auth-context";

describe("useAuth", () => {
  it("выбрасывает ошибку вне провайдера", () => {
    expect(() => renderHook(() => useAuth())).toThrow(
      "useAuth должен использоваться внутри <AuthProvider>",
    );
  });

  it("возвращает значение контекста внутри провайдера", () => {
    const value: AuthContextValue = {
      user: null,
      isLoading: false,
      isAuthenticated: false,
      login: async () => {},
      logout: async () => {},
    };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current).toBe(value);
  });
});
