import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError } from "axios";
import { renderWithProviders } from "@tests/utils";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigate };
});

const login = vi.fn();
let authState = { isAuthenticated: false };
vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({ login, isAuthenticated: authState.isAuthenticated }),
}));

import { LoginPage } from "@/pages/Login";

beforeEach(() => {
  vi.clearAllMocks();
  authState = { isAuthenticated: false };
  login.mockResolvedValue(undefined);
});

describe("LoginPage", () => {
  it("renders the login form", () => {
    renderWithProviders(<LoginPage />);
    expect(screen.getByText("LocalCloud")).toBeInTheDocument();
    expect(screen.getByLabelText("Email или имя пользователя")).toBeInTheDocument();
    expect(screen.getByLabelText("Пароль")).toBeInTheDocument();
  });

  it("submits credentials and navigates on success", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />);
    await user.type(screen.getByLabelText("Email или имя пользователя"), "alice");
    await user.type(screen.getByLabelText("Пароль"), "secret123");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith({ email_or_username: "alice", password: "secret123" }),
    );
    expect(navigate).toHaveBeenCalledWith("/files", { replace: true });
  });

  it("shows invalid-credentials error on 401", async () => {
    const err = new AxiosError("unauth");
    // @ts-expect-error partial response stub
    err.response = { status: 401 };
    login.mockRejectedValueOnce(err);
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />);
    await user.type(screen.getByLabelText("Email или имя пользователя"), "alice");
    await user.type(screen.getByLabelText("Пароль"), "bad");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Неверный логин или пароль.")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("shows generic error on non-401 failure", async () => {
    login.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />);
    await user.type(screen.getByLabelText("Email или имя пользователя"), "alice");
    await user.type(screen.getByLabelText("Пароль"), "pw");
    await user.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByText("Произошла ошибка. Попробуйте позже.")).toBeInTheDocument();
  });

  it("redirects immediately when already authenticated", () => {
    authState = { isAuthenticated: true };
    const { container } = renderWithProviders(<LoginPage />);
    expect(navigate).toHaveBeenCalledWith("/files", { replace: true });
    expect(container).toBeEmptyDOMElement();
  });
});
