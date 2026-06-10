import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError } from "axios";
import { renderWithProviders } from "@/test/utils";

vi.mock("@/api/registration", () => ({
  registrationApi: { create: vi.fn() },
}));

import { registrationApi } from "@/api/registration";
import { RegisterPage } from "./Register";

const create = vi.mocked(registrationApi.create);

async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
  { password = "password123", confirm = "password123" } = {},
) {
  await user.type(screen.getByLabelText("Email"), "bob@example.com");
  await user.type(screen.getByLabelText("Имя пользователя"), "bob_123");
  await user.type(screen.getByLabelText("Пароль"), password);
  await user.type(screen.getByLabelText("Подтвердите пароль"), confirm);
}

beforeEach(() => {
  vi.clearAllMocks();
  create.mockResolvedValue({} as never);
});

describe("RegisterPage", () => {
  it("renders the registration form", () => {
    renderWithProviders(<RegisterPage />);
    expect(screen.getByText("Регистрация")).toBeInTheDocument();
  });

  it("submits and shows success screen", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Отправить заявку" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        email: "bob@example.com",
        username: "bob_123",
        password: "password123",
      }),
    );
    expect(await screen.findByText("Заявка отправлена")).toBeInTheDocument();
  });

  it("validates short password without calling the api", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    await fillForm(user, { password: "short", confirm: "short" });
    await user.click(screen.getByRole("button", { name: "Отправить заявку" }));

    expect(
      await screen.findByText("Пароль должен содержать не менее 8 символов."),
    ).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("validates mismatched passwords", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    await fillForm(user, { password: "password123", confirm: "different1" });
    await user.click(screen.getByRole("button", { name: "Отправить заявку" }));

    expect(await screen.findByText("Пароли не совпадают.")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("shows server detail string on error", async () => {
    const err = new AxiosError("bad");
    // @ts-expect-error partial response stub
    err.response = { data: { detail: "Email занят" } };
    create.mockRejectedValueOnce(err);
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Отправить заявку" }));

    expect(await screen.findByText("Email занят")).toBeInTheDocument();
  });

  it("joins validation detail array", async () => {
    const err = new AxiosError("bad");
    // @ts-expect-error partial response stub
    err.response = { data: { detail: [{ msg: "ошибка1" }, { msg: "ошибка2" }] } };
    create.mockRejectedValueOnce(err);
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Отправить заявку" }));

    expect(await screen.findByText("ошибка1 ошибка2")).toBeInTheDocument();
  });

  it("shows conflict message on 409", async () => {
    const err = new AxiosError("conflict");
    // @ts-expect-error partial response stub
    err.response = { status: 409, data: {} };
    create.mockRejectedValueOnce(err);
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Отправить заявку" }));

    expect(
      await screen.findByText("Пользователь с таким email или именем уже существует."),
    ).toBeInTheDocument();
  });

  it("shows generic error on non-axios failure", async () => {
    create.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Отправить заявку" }));

    expect(await screen.findByText("Произошла ошибка. Попробуйте позже.")).toBeInTheDocument();
  });

  it("toggles password visibility", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />);
    const pwd = screen.getByLabelText("Пароль");
    expect(pwd).toHaveAttribute("type", "password");
    // The visibility toggle is the unlabeled button next to the password input
    const toggle = pwd.parentElement!.querySelector("button")!;
    await user.click(toggle);
    expect(pwd).toHaveAttribute("type", "text");
  });
});
