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
  authApi: { requestPasswordReset: vi.fn() },
}));

import { authApi } from "@/api/auth";
import { ForgotPasswordPage } from "@/pages/ForgotPassword";

const requestPasswordReset = vi.mocked(authApi.requestPasswordReset);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ForgotPasswordPage", () => {
  it("requests reset and shows token", async () => {
    requestPasswordReset.mockResolvedValue({ reset_token: "tok-123" } as never);
    const user = userEvent.setup();
    renderWithProviders(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.click(screen.getByRole("button", { name: "Отправить" }));

    await waitFor(() =>
      expect(requestPasswordReset).toHaveBeenCalledWith({ email: "a@b.com" }),
    );
    expect(await screen.findByText("Токен сброса сгенерирован")).toBeInTheDocument();
    expect(screen.getByDisplayValue("tok-123")).toBeInTheDocument();
  });

  it("copies token to clipboard", async () => {
    requestPasswordReset.mockResolvedValue({ reset_token: "tok-xyz" } as never);
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    // Override clipboard AFTER userEvent.setup so the page sees our spy, not
    // userEvent's internal stub.
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    renderWithProviders(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    await screen.findByDisplayValue("tok-xyz");

    await user.click(screen.getByTitle("Копировать"));
    expect(writeText).toHaveBeenCalledWith("tok-xyz");
  });

  it("navigates to reset page with the token", async () => {
    requestPasswordReset.mockResolvedValue({ reset_token: "tok abc" } as never);
    const user = userEvent.setup();
    renderWithProviders(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    await screen.findByText("Токен сброса сгенерирован");

    await user.click(screen.getByRole("button", { name: "Установить новый пароль" }));
    expect(navigate).toHaveBeenCalledWith("/reset-password?token=tok%20abc");
  });

  it("shows api detail error", async () => {
    const err = new AxiosError("bad");
    // @ts-expect-error partial response stub
    err.response = { data: { detail: "Пользователь не найден" } };
    requestPasswordReset.mockRejectedValueOnce(err);
    const user = userEvent.setup();
    renderWithProviders(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.click(screen.getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText("Пользователь не найден")).toBeInTheDocument();
  });

  it("shows generic error on non-axios failure", async () => {
    requestPasswordReset.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    renderWithProviders(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.click(screen.getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText("Произошла ошибка. Попробуйте позже.")).toBeInTheDocument();
  });
});
