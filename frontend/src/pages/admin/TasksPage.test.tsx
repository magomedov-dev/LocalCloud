import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import type { BackgroundTaskListItem, BackgroundTaskStatus } from "@/types/tasks";

const tasksApi = vi.hoisted(() => ({ list: vi.fn(), cancel: vi.fn() }));
vi.mock("@/api/tasks", () => ({ tasksApi }));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

import { TasksPage } from "./TasksPage";

function makeTask(over: Partial<BackgroundTaskListItem> = {}): BackgroundTaskListItem {
  return {
    id: "task-1",
    task_type: "clean_trash",
    status: "pending",
    priority: "normal",
    created_by: null,
    related_entity_type: null,
    related_entity_id: null,
    progress_percent: 0,
    error_code: null,
    attempts_count: 0,
    max_attempts: 3,
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-01-01T09:00:00Z",
    updated_at: "2026-01-01T09:00:00Z",
    ...over,
  };
}

function page(items: BackgroundTaskListItem[], total = items.length) {
  return { items, meta: { total, limit: 20, offset: 0 } };
}

beforeEach(() => {
  vi.clearAllMocks();
  tasksApi.list.mockResolvedValue(page([]));
  tasksApi.cancel.mockResolvedValue({});
});

describe("TasksPage", () => {
  it("renders task rows with localized status labels", async () => {
    const statuses: BackgroundTaskStatus[] = [
      "pending",
      "running",
      "completed",
      "failed",
      "cancelled",
    ];
    tasksApi.list.mockResolvedValue(
      page(statuses.map((s, i) => makeTask({ id: `t${i}`, status: s }))),
    );
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText("Ожидает")).toBeInTheDocument();
    expect(screen.getByText("Выполняется")).toBeInTheDocument();
    expect(screen.getByText("Завершена")).toBeInTheDocument();
    expect(screen.getByText("Ошибка")).toBeInTheDocument();
    expect(screen.getByText("Отменена")).toBeInTheDocument();
  });

  it("renders dash for missing started_at and shows task type", async () => {
    tasksApi.list.mockResolvedValue(page([makeTask()]));
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText("clean_trash")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows a cancel button only for pending/running tasks", async () => {
    tasksApi.list.mockResolvedValue(
      page([
        makeTask({ id: "a", status: "running" }),
        makeTask({ id: "b", status: "completed" }),
      ]),
    );
    renderWithProviders(<TasksPage />);

    await screen.findByText("Выполняется");
    // Only one cancel button (for the running task).
    expect(screen.getAllByTitle("Отменить")).toHaveLength(1);
  });

  it("cancels a task and shows a success toast", async () => {
    const user = userEvent.setup();
    tasksApi.list.mockResolvedValue(page([makeTask({ status: "running" })]));
    renderWithProviders(<TasksPage />);

    await user.click(await screen.findByTitle("Отменить"));

    await waitFor(() => expect(tasksApi.cancel).toHaveBeenCalledWith("task-1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Задача отменена"));
  });

  it("shows an error toast when cancel fails", async () => {
    const user = userEvent.setup();
    tasksApi.cancel.mockRejectedValue(new Error("nope"));
    tasksApi.list.mockResolvedValue(page([makeTask({ status: "running" })]));
    renderWithProviders(<TasksPage />);

    await user.click(await screen.findByTitle("Отменить"));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось отменить задачу"),
    );
  });

  it("shows the empty state when there are no tasks", async () => {
    tasksApi.list.mockResolvedValue(page([]));
    renderWithProviders(<TasksPage />);

    expect(await screen.findByText("Задач нет.")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    let resolve!: (v: ReturnType<typeof page>) => void;
    tasksApi.list.mockReturnValue(new Promise((r) => (resolve = r)));
    const { container } = renderWithProviders(<TasksPage />);

    expect(container.querySelectorAll("table tbody tr").length).toBe(6);
    resolve(page([]));
  });

  it("filters by status and resets to first page", async () => {
    const user = userEvent.setup();
    tasksApi.list.mockResolvedValue(page([makeTask()]));
    renderWithProviders(<TasksPage />);

    await screen.findByText("clean_trash");
    await user.click(screen.getByRole("button", { name: "С ошибкой" }));

    await waitFor(() =>
      expect(tasksApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", offset: 0 }),
      ),
    );
  });

  it("paginates across pages", async () => {
    const user = userEvent.setup();
    tasksApi.list.mockResolvedValue(page([makeTask()], 50));
    renderWithProviders(<TasksPage />);

    await screen.findByText("clean_trash");
    expect(screen.getByText(/Стр\. 1 \/ 3/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Вперёд/ }));

    await waitFor(() =>
      expect(tasksApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 20 }),
      ),
    );
  });
});
