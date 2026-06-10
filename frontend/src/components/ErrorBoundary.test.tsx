import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom({ message }: { message?: string }): never {
  throw new Error(message ?? "");
}

describe("ErrorBoundary", () => {
  it("рендерит детей без ошибки", () => {
    render(
      <ErrorBoundary>
        <p>содержимое</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("содержимое")).toBeInTheDocument();
  });

  it("показывает fallback с сообщением ошибки", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom message="сломалось" />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Что-то пошло не так")).toBeInTheDocument();
    expect(screen.getByText("сломалось")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("показывает дефолтный текст, когда у ошибки нет сообщения", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/непредвиденная ошибка/i)).toBeInTheDocument();
    spy.mockRestore();
  });

  it("обрабатывает клик по кнопке «Попробовать снова»", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom message="опять" />
      </ErrorBoundary>,
    );
    const button = screen.getByRole("button", { name: /попробовать снова/i });
    // Клик вызывает setState({ error: null }); дочерний компонент снова бросает,
    // поэтому fallback остаётся — нам важно покрыть обработчик onClick.
    await userEvent.click(button);
    expect(screen.getByText("Что-то пошло не так")).toBeInTheDocument();
    spy.mockRestore();
  });
});
