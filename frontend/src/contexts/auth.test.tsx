import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AuthProvider } from "./auth";
import { useAuth } from "./auth-context";

vi.mock("@/api/auth", () => ({
  authApi: {
    me: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

const clearMock = vi.fn();
vi.mock("@/lib/query-client", () => ({
  queryClient: { clear: () => clearMock() },
}));

import { authApi } from "@/api/auth";

const meMock = vi.mocked(authApi.me);
const loginMock = vi.mocked(authApi.login);
const logoutMock = vi.mocked(authApi.logout);

const sampleUser = { id: "u1", email: "a@b.c", username: "user" } as never;

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  meMock.mockResolvedValue(sampleUser);
  loginMock.mockResolvedValue({ user: sampleUser } as never);
  logoutMock.mockResolvedValue({} as never);
});

describe("AuthProvider", () => {
  it("стартует в состоянии загрузки и загружает текущего пользователя", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.user).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.user).toBe(sampleUser);
    expect(result.current.isAuthenticated).toBe(true);
    expect(meMock).toHaveBeenCalledTimes(1);
  });

  it("остаётся неавторизованным, если загрузка сессии не удалась", async () => {
    meMock.mockRejectedValueOnce(new Error("401"));
    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);
  });

  it("login сохраняет пользователя при успехе", async () => {
    meMock.mockRejectedValueOnce(new Error("no session"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.login({ login: "user", password: "pw" } as never);
    });

    expect(loginMock).toHaveBeenCalledWith({ login: "user", password: "pw" });
    expect(result.current.user).toBe(sampleUser);
    expect(result.current.isAuthenticated).toBe(true);
  });

  it("login пробрасывает ошибку при неудаче", async () => {
    meMock.mockRejectedValueOnce(new Error("no session"));
    loginMock.mockRejectedValueOnce(new Error("bad creds"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(
      act(async () => {
        await result.current.login({ login: "user", password: "wrong" } as never);
      }),
    ).rejects.toThrow("bad creds");
    expect(result.current.user).toBeNull();
  });

  it("logout очищает пользователя, кэш и перенаправляет на /login", async () => {
    const replaceMock = vi.fn();
    const original = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...original, replace: replaceMock },
    });

    try {
      const { result } = renderHook(() => useAuth(), { wrapper });
      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.user).toBe(sampleUser);

      await act(async () => {
        await result.current.logout();
      });

      expect(logoutMock).toHaveBeenCalledTimes(1);
      expect(result.current.user).toBeNull();
      expect(clearMock).toHaveBeenCalledTimes(1);
      expect(replaceMock).toHaveBeenCalledWith("/login");
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: original });
    }
  });

  it("logout завершается даже при ошибке API выхода", async () => {
    logoutMock.mockRejectedValueOnce(new Error("server down"));
    const replaceMock = vi.fn();
    const original = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...original, replace: replaceMock },
    });

    try {
      const { result } = renderHook(() => useAuth(), { wrapper });
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      await act(async () => {
        await result.current.logout();
      });

      expect(result.current.user).toBeNull();
      expect(replaceMock).toHaveBeenCalledWith("/login");
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: original });
    }
  });
});
