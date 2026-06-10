import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import { authApi } from "@/api/auth";

beforeEach(() => vi.clearAllMocks());

describe("authApi", () => {
  it("login posts credentials to /auth/login", async () => {
    const expected = { user: { id: "u1" } };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { login: "user@example.com", password: "pw" } as never;
    const result = await authApi.login(data);
    expect(mockApi.post).toHaveBeenCalledWith("/auth/login", data);
    expect(result).toEqual(expected);
  });

  it("logout posts to /auth/logout", async () => {
    const expected = { message: "ok" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const result = await authApi.logout();
    expect(mockApi.post).toHaveBeenCalledWith("/auth/logout");
    expect(result).toEqual(expected);
  });

  it("me gets /auth/me", async () => {
    const expected = { id: "u1", email: "u@e.com" };
    mockApi.get.mockResolvedValueOnce({ data: expected });
    const result = await authApi.me();
    expect(mockApi.get).toHaveBeenCalledWith("/auth/me");
    expect(result).toEqual(expected);
  });

  it("changePassword posts to /auth/password/change", async () => {
    const expected = { message: "changed" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { current_password: "old", new_password: "new" } as never;
    const result = await authApi.changePassword(data);
    expect(mockApi.post).toHaveBeenCalledWith("/auth/password/change", data);
    expect(result).toEqual(expected);
  });

  it("requestPasswordReset posts to /auth/password/reset/request", async () => {
    const expected = { reset_token: "t", expires_at: "now" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { email: "u@e.com" } as never;
    const result = await authApi.requestPasswordReset(data);
    expect(mockApi.post).toHaveBeenCalledWith("/auth/password/reset/request", data);
    expect(result).toEqual(expected);
  });

  it("confirmPasswordReset posts to /auth/password/reset/confirm", async () => {
    const expected = { message: "done" };
    mockApi.post.mockResolvedValueOnce({ data: expected });
    const data = { reset_token: "t", new_password: "new" } as never;
    const result = await authApi.confirmPasswordReset(data);
    expect(mockApi.post).toHaveBeenCalledWith("/auth/password/reset/confirm", data);
    expect(result).toEqual(expected);
  });
});
