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

vi.mock("@/api/auth", () => ({
  authApi: { confirmPasswordReset: vi.fn() },
}));

import { authApi } from "@/api/auth";
import { ResetPasswordPage } from "@/pages/ResetPassword";

const confirmPasswordReset = vi.mocked(authApi.confirmPasswordReset);

beforeEach(() => {
  vi.clearAllMocks();
  confirmPasswordReset.mockResolvedValue({} as never);
});

describe("ResetPasswordPage", () => {
  it("hides the token field when token is in the URL and submits", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password?token=abc"] });
    expect(screen.queryByLabelText("Токен сброса")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Новый пароль"), "password123");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "password123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(confirmPasswordReset).toHaveBeenCalledWith({
        token: "abc",
        new_password: "password123",
      }),
    );
    expect(await screen.findByText("Пароль изменён")).toBeInTheDocument();
  });

  it("navigates to login from success screen", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password?token=abc"] });
    await user.type(screen.getByLabelText("Новый пароль"), "password123");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "password123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await screen.findByText("Пароль изменён");

    await user.click(screen.getByRole("button", { name: "Войти" }));
    expect(navigate).toHaveBeenCalledWith("/login");
  });

  it("shows the editable token field when URL has no token", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password"] });
    const tokenField = screen.getByLabelText("Токен сброса");
    expect(tokenField).toBeInTheDocument();

    await user.type(tokenField, "manual-token");
    await user.type(screen.getByLabelText("Новый пароль"), "password123");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "password123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(confirmPasswordReset).toHaveBeenCalledWith({
        token: "manual-token",
        new_password: "password123",
      }),
    );
  });

  it("validates short password", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password?token=abc"] });
    await user.type(screen.getByLabelText("Новый пароль"), "short");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "short");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(
      await screen.findByText("Пароль должен содержать не менее 8 символов."),
    ).toBeInTheDocument();
    expect(confirmPasswordReset).not.toHaveBeenCalled();
  });

  it("validates mismatched passwords", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password?token=abc"] });
    await user.type(screen.getByLabelText("Новый пароль"), "password123");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "different1");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Пароли не совпадают.")).toBeInTheDocument();
  });

  it("shows 400 error message", async () => {
    const err = new AxiosError("bad");
    // @ts-expect-error partial response stub
    err.response = { status: 400, data: {} };
    confirmPasswordReset.mockRejectedValueOnce(err);
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password?token=abc"] });
    await user.type(screen.getByLabelText("Новый пароль"), "password123");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "password123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Токен недействителен или истёк.")).toBeInTheDocument();
  });

  it("shows server detail string error", async () => {
    const err = new AxiosError("bad");
    // @ts-expect-error partial response stub
    err.response = { status: 422, data: { detail: "Спец. ошибка" } };
    confirmPasswordReset.mockRejectedValueOnce(err);
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password?token=abc"] });
    await user.type(screen.getByLabelText("Новый пароль"), "password123");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "password123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Спец. ошибка")).toBeInTheDocument();
  });

  it("shows generic error on non-axios failure", async () => {
    confirmPasswordReset.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    renderWithProviders(<ResetPasswordPage />, { routerEntries: ["/reset-password?token=abc"] });
    await user.type(screen.getByLabelText("Новый пароль"), "password123");
    await user.type(screen.getByLabelText("Подтвердите пароль"), "password123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Произошла ошибка. Попробуйте позже.")).toBeInTheDocument();
  });
});
