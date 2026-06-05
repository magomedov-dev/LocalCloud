import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadPanel } from "@/components/files/UploadPanel";
import type { UploadTask, UploadContextValue } from "@/contexts/upload-context";

const useUploadMock = vi.fn<() => UploadContextValue>();

vi.mock("@/contexts/upload-context", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/upload-context")>();
  return { ...actual, useUpload: () => useUploadMock() };
});

function task(overrides: Partial<UploadTask> = {}): UploadTask {
  return {
    id: "t1",
    filename: "file.txt",
    progress: 0,
    status: "pending",
    error: null,
    ...overrides,
  };
}

function setContext(tasks: UploadTask[]) {
  const dismiss = vi.fn();
  const dismissAllDone = vi.fn();
  useUploadMock.mockReturnValue({
    tasks,
    enqueue: vi.fn(),
    dismiss,
    dismissAllDone,
  });
  return { dismiss, dismissAllDone };
}

describe("UploadPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ничего не рендерит при пустом списке задач", () => {
    setContext([]);
    const { container } = render(<UploadPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("показывает счётчик активных загрузок и спиннер", () => {
    setContext([task({ id: "a", status: "uploading", progress: 40 })]);
    render(<UploadPanel />);
    expect(screen.getByText("Загрузка файлов (1)")).toBeInTheDocument();
    expect(screen.getByText("file.txt")).toBeInTheDocument();
  });

  it("показывает заголовок «Загрузки», когда нет активных", () => {
    setContext([task({ id: "a", status: "done", progress: 100 })]);
    render(<UploadPanel />);
    expect(screen.getByText("Загрузки")).toBeInTheDocument();
  });

  it("показывает текст ошибки для ошибочной задачи", () => {
    setContext([task({ id: "a", status: "error", error: "Сбой загрузки" })]);
    render(<UploadPanel />);
    expect(screen.getByText("Сбой загрузки")).toBeInTheDocument();
  });

  it("вызывает dismiss при клике на кнопку завершённой задачи", async () => {
    const user = userEvent.setup();
    const { dismiss } = setContext([task({ id: "a", status: "done", progress: 100 })]);
    render(<UploadPanel />);
    await user.click(screen.getByRole("button", { name: "Убрать" }));
    expect(dismiss).toHaveBeenCalledWith("a");
  });

  it("вызывает dismiss для ошибочной задачи", async () => {
    const user = userEvent.setup();
    const { dismiss } = setContext([task({ id: "e", status: "error", error: "x" })]);
    render(<UploadPanel />);
    await user.click(screen.getByRole("button", { name: "Убрать" }));
    expect(dismiss).toHaveBeenCalledWith("e");
  });

  it("не показывает кнопку скрытия для активной задачи", () => {
    setContext([task({ id: "a", status: "uploading", progress: 10 })]);
    render(<UploadPanel />);
    expect(screen.queryByRole("button", { name: "Убрать" })).not.toBeInTheDocument();
  });

  it("показывает кнопку массового закрытия при более чем одной завершённой задаче", async () => {
    const user = userEvent.setup();
    const { dismissAllDone } = setContext([
      task({ id: "a", status: "done", progress: 100 }),
      task({ id: "b", status: "error", error: "x" }),
    ]);
    render(<UploadPanel />);
    await user.click(screen.getByRole("button", { name: "Закрыть завершённые" }));
    expect(dismissAllDone).toHaveBeenCalled();
  });

  it("не показывает кнопку массового закрытия при одной завершённой задаче", () => {
    setContext([task({ id: "a", status: "done", progress: 100 })]);
    render(<UploadPanel />);
    expect(
      screen.queryByRole("button", { name: "Закрыть завершённые" }),
    ).not.toBeInTheDocument();
  });

  it("рендерит строку для каждой задачи", () => {
    setContext([
      task({ id: "a", filename: "one.txt", status: "uploading", progress: 30 }),
      task({ id: "b", filename: "two.txt", status: "done", progress: 100 }),
    ]);
    render(<UploadPanel />);
    expect(screen.getByText("one.txt")).toBeInTheDocument();
    expect(screen.getByText("two.txt")).toBeInTheDocument();
  });

  it("показывает прогресс-бар для загружаемой задачи вместо текста ошибки", () => {
    setContext([task({ id: "a", status: "uploading", progress: 55, error: null })]);
    render(<UploadPanel />);
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });
});
