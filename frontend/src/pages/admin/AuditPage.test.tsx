import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import type { AuditLog } from "@/types/audit";

const auditApi = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/api/audit", () => ({ auditApi }));

import { AuditPage } from "./AuditPage";

function makeLog(over: Partial<AuditLog> = {}): AuditLog {
  return {
    id: "log-1",
    user_id: "user-1",
    action: "user.login",
    result: "success",
    entity_type: "user",
    entity_id: "e1",
    resource_type: "session",
    request_id: "req-1",
    ip_address: "10.0.0.1",
    user_agent: "jsdom",
    message: "Вход выполнен",
    error_code: "ERR_X",
    metadata: null,
    created_at: "2026-01-01T10:00:00Z",
    ...over,
  };
}

function page(items: AuditLog[], total = items.length) {
  return { items, meta: { total, limit: 25, offset: 0 } };
}

beforeEach(() => {
  vi.clearAllMocks();
  auditApi.list.mockResolvedValue(page([]));
});

describe("AuditPage", () => {
  it("renders a row with action, result label, resource and message", async () => {
    auditApi.list.mockResolvedValue(page([makeLog()]));
    const { container } = renderWithProviders(<AuditPage />);

    expect(await screen.findByText("user.login")).toBeInTheDocument();
    // "Успех" also appears as a filter button; assert the row badge specifically.
    const table = container.querySelector("table")!;
    expect(within(table).getByText("Успех")).toBeInTheDocument();
    expect(screen.getByText("session")).toBeInTheDocument();
    expect(screen.getByText("Вход выполнен")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
  });

  it("falls back to raw result and dashes for nullable fields", async () => {
    auditApi.list.mockResolvedValue(
      page([
        makeLog({
          result: "unknown",
          resource_type: null,
          message: null,
          ip_address: null,
        }),
      ]),
    );
    renderWithProviders(<AuditPage />);

    expect(await screen.findByText("unknown")).toBeInTheDocument();
    // resource, message, ip all render the em dash placeholder.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("expands a row on click to reveal extra detail", async () => {
    const user = userEvent.setup();
    auditApi.list.mockResolvedValue(page([makeLog()]));
    renderWithProviders(<AuditPage />);

    const actionCell = await screen.findByText("user.login");
    expect(screen.queryByText(/request_id:/)).not.toBeInTheDocument();

    await user.click(actionCell);

    expect(screen.getByText("user_id:")).toBeInTheDocument();
    expect(screen.getByText("entity:")).toBeInTheDocument();
    expect(screen.getByText("error_code:")).toBeInTheDocument();
    expect(screen.getByText("request_id:")).toBeInTheDocument();

    // Click again collapses.
    await user.click(actionCell);
    await waitFor(() =>
      expect(screen.queryByText("request_id:")).not.toBeInTheDocument(),
    );
  });

  it("shows the empty state when there are no logs", async () => {
    auditApi.list.mockResolvedValue(page([]));
    renderWithProviders(<AuditPage />);

    expect(await screen.findByText("Записей нет.")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    let resolve!: (v: ReturnType<typeof page>) => void;
    auditApi.list.mockReturnValue(new Promise((r) => (resolve = r)));
    const { container } = renderWithProviders(<AuditPage />);

    expect(container.querySelectorAll("table tbody tr").length).toBe(8);
    expect(screen.queryByText("Записей нет.")).not.toBeInTheDocument();
    resolve(page([]));
  });

  it("filters by result and resets to first page", async () => {
    const user = userEvent.setup();
    auditApi.list.mockResolvedValue(page([makeLog()]));
    renderWithProviders(<AuditPage />);

    await screen.findByText("user.login");
    await user.click(screen.getByRole("button", { name: "Ошибка" }));

    await waitFor(() =>
      expect(auditApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ result: "failure", offset: 0 }),
      ),
    );
  });

  it("filters by free-text query", async () => {
    const user = userEvent.setup();
    auditApi.list.mockResolvedValue(page([makeLog()]));
    renderWithProviders(<AuditPage />);

    await screen.findByText("user.login");
    await user.type(screen.getByPlaceholderText("Поиск по сообщению…"), "boom");

    await waitFor(() =>
      expect(auditApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: "boom" }),
      ),
    );
  });

  it("paginates when total exceeds the page size", async () => {
    const user = userEvent.setup();
    auditApi.list.mockResolvedValue(page([makeLog()], 60));
    renderWithProviders(<AuditPage />);

    await screen.findByText("user.login");
    expect(screen.getByText(/Стр\. 1 \/ 3/)).toBeInTheDocument();

    const back = screen.getByRole("button", { name: /Назад/ });
    expect(back).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Вперёд/ }));

    await waitFor(() =>
      expect(auditApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 25 }),
      ),
    );
    expect(screen.getByText(/Стр\. 2 \/ 3/)).toBeInTheDocument();
  });

  it("shows an empty state (not an error UI) when the query rejects", async () => {
    auditApi.list.mockRejectedValue(new Error("boom"));
    renderWithProviders(<AuditPage />);

    expect(await screen.findByText("Записей нет.")).toBeInTheDocument();
  });

  it("collapses detail to dashes when expanded row has no optional fields", async () => {
    const user = userEvent.setup();
    auditApi.list.mockResolvedValue(
      page([
        makeLog({
          user_id: null,
          entity_type: null,
          error_code: null,
          request_id: null,
        }),
      ]),
    );
    const { container } = renderWithProviders(<AuditPage />);

    const actionCell = await screen.findByText("user.login");
    await user.click(actionCell);

    // Expanded row exists but contains none of the labelled fields.
    const detail = within(container).queryByText("request_id:");
    expect(detail).not.toBeInTheDocument();
  });
});
