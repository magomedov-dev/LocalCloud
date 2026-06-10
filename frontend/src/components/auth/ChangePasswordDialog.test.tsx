import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { renderWithProviders } from "@/test/utils";
import { ChangePasswordDialog } from "./ChangePasswordDialog";

const changePassword = vi.hoisted(() => vi.fn());

vi.mock("@/api/auth", () => ({
  authApi: { changePassword: (...args: unknown[]) => changePassword(...args) },
}));

function makeAxiosError(status: number, detail?: unknown): AxiosError {
  const err = new AxiosError("fail");
  err.response = {
    data: detail === undefined ? {} : { detail },
    status,
    statusText: "",
    headers: {},
    config: { headers: new AxiosHeaders() },
  };
  return err;
}

function renderDialog() {
  return renderWithProviders(<ChangePasswordDialog open onOpenChange={vi.fn()} />);
}

async function fill(current: string, next: string, confirm: string) {
  renderDialog();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Текущий пароль"), current);
  await user.type(screen.getByLabelText("Новый пароль"), next);
  await user.type(screen.getByLabelText("Подтвердите новый пароль"), confirm);
  return user;
}

describe("ChangePasswordDialog", () => {
  beforeEach(() => {
    changePassword.mockReset();
  });

  it("рендерит поля формы в открытом состоянии", () => {
    renderDialog();
    expect(screen.getByText("Сменить пароль")).toBeInTheDocument();
    expect(screen.getByLabelText("Текущий пароль")).toBeInTheDocument();
    expect(screen.getByLabelText("Новый пароль")).toBeInTheDocument();
    expect(screen.getByLabelText("Подтвердите новый пароль")).toBeInTheDocument();
  });

  it("успешно меняет пароль и показывает сообщение", async () => {
    changePassword.mockResolvedValue({});
    const user = await fill("oldpass123", "newpass123", "newpass123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(screen.getByText("Пароль успешно изменён.")).toBeInTheDocument(),
    );
    expect(changePassword).toHaveBeenCalledWith({
      current_password: "oldpass123",
      new_password: "newpass123",
    });
    expect(screen.getByRole("button", { name: "Закрыть" })).toBeInTheDocument();
  });

  it("валидирует минимальную длину нового пароля", async () => {
    const user = await fill("oldpass123", "short", "short");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(
      await screen.findByText("Новый пароль должен содержать не менее 8 символов."),
    ).toBeInTheDocument();
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("валидирует несовпадение паролей", async () => {
    const user = await fill("oldpass123", "newpass123", "different123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Пароли не совпадают.")).toBeInTheDocument();
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("показывает detail-сообщение из ошибки axios", async () => {
    changePassword.mockRejectedValue(makeAxiosError(422, "Пароль слишком слабый"));
    const user = await fill("oldpass123", "newpass123", "newpass123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Пароль слишком слабый")).toBeInTheDocument();
  });

  it("показывает сообщение про неверный текущий пароль для 400 без detail", async () => {
    changePassword.mockRejectedValue(makeAxiosError(400));
    const user = await fill("oldpass123", "newpass123", "newpass123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Неверный текущий пароль.")).toBeInTheDocument();
  });

  it("показывает общее сообщение для прочих axios-ошибок", async () => {
    changePassword.mockRejectedValue(makeAxiosError(500));
    const user = await fill("oldpass123", "newpass123", "newpass123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(
      await screen.findByText("Произошла ошибка. Попробуйте позже."),
    ).toBeInTheDocument();
  });

  it("показывает общее сообщение для не-axios ошибки", async () => {
    changePassword.mockRejectedValue(new Error("boom"));
    const user = await fill("oldpass123", "newpass123", "newpass123");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(
      await screen.findByText("Произошла ошибка. Попробуйте позже."),
    ).toBeInTheDocument();
  });

  it("переключает видимость текущего пароля", async () => {
    const user = userEvent.setup();
    renderDialog();
    const input = screen.getByLabelText("Текущий пароль");
    expect(input).toHaveAttribute("type", "password");
    // Кнопка-глаз — соседний button без имени внутри обёртки поля.
    const toggle = input.parentElement!.querySelector("button")!;
    await user.click(toggle);
    expect(input).toHaveAttribute("type", "text");
  });

  it("переключает видимость нового пароля", async () => {
    const user = userEvent.setup();
    renderDialog();
    const input = screen.getByLabelText("Новый пароль");
    expect(input).toHaveAttribute("type", "password");
    const toggle = input.parentElement!.querySelector("button")!;
    await user.click(toggle);
    expect(input).toHaveAttribute("type", "text");
  });

  it("блокирует кнопку и показывает индикатор во время отправки", async () => {
    let resolve: (() => void) | undefined;
    changePassword.mockReturnValue(new Promise<void>((r) => (resolve = () => r())));
    const user = await fill("oldpass123", "newpass123", "newpass123");
    const submit = screen.getByRole("button", { name: "Сохранить" });
    await user.click(submit);

    await waitFor(() => expect(submit).toBeDisabled());
    resolve?.();
  });
});
