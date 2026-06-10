import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import type { RegistrationRead, RegistrationStatus } from "@/types/registration";

const registrationApi = vi.hoisted(() => ({
  list: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
}));
vi.mock("@/api/registration", () => ({ registrationApi }));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

import { RegistrationPage } from "./RegistrationPage";

function makeReq(over: Partial<RegistrationRead> = {}): RegistrationRead {
  return {
    id: "req-1",
    email: "new@example.com",
    username: "newbie",
    status: "pending",
    comment: null,
    reviewed_by: null,
    reviewed_at: null,
    created_at: "2026-01-01T08:00:00Z",
    ...over,
  };
}

function page(items: RegistrationRead[], total = items.length) {
  return { items, meta: { total, limit: 20, offset: 0 } };
}

beforeEach(() => {
  vi.clearAllMocks();
  registrationApi.list.mockResolvedValue(page([]));
  registrationApi.approve.mockResolvedValue({});
  registrationApi.reject.mockResolvedValue({});
});

describe("RegistrationPage", () => {
  it("defaults to the pending filter and renders pending rows", async () => {
    registrationApi.list.mockResolvedValue(page([makeReq()]));
    renderWithProviders(<RegistrationPage />);

    expect(await screen.findByText("new@example.com")).toBeInTheDocument();
    expect(screen.getByText("@newbie")).toBeInTheDocument();
    expect(screen.getByText("Ожидает")).toBeInTheDocument();
    expect(registrationApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ status: "pending" }),
    );
    // Action buttons present for pending rows.
    expect(screen.getByTitle("Одобрить")).toBeInTheDocument();
    expect(screen.getByTitle("Отклонить")).toBeInTheDocument();
  });

  it("hides action buttons for non-pending rows", async () => {
    registrationApi.list.mockResolvedValue(page([makeReq({ status: "approved" })]));
    renderWithProviders(<RegistrationPage />);

    await screen.findByText("new@example.com");
    expect(screen.getByText("Одобрена")).toBeInTheDocument();
    expect(screen.queryByTitle("Одобрить")).not.toBeInTheDocument();
  });

  it("approves a request and shows a success toast", async () => {
    const user = userEvent.setup();
    registrationApi.list.mockResolvedValue(page([makeReq()]));
    renderWithProviders(<RegistrationPage />);

    await user.click(await screen.findByTitle("Одобрить"));

    await waitFor(() => expect(registrationApi.approve).toHaveBeenCalledWith("req-1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Заявка одобрена"));
  });

  it("shows an error toast when approve fails", async () => {
    const user = userEvent.setup();
    registrationApi.approve.mockRejectedValue(new Error("nope"));
    registrationApi.list.mockResolvedValue(page([makeReq()]));
    renderWithProviders(<RegistrationPage />);

    await user.click(await screen.findByTitle("Одобрить"));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось одобрить заявку"),
    );
  });

  it("rejects a request through the dialog with a reason", async () => {
    const user = userEvent.setup();
    registrationApi.list.mockResolvedValue(page([makeReq()]));
    renderWithProviders(<RegistrationPage />);

    await user.click(await screen.findByTitle("Отклонить"));

    // Dialog opens with the email in the title.
    expect(
      await screen.findByText("Отклонить заявку — new@example.com"),
    ).toBeInTheDocument();

    const submit = screen.getByRole("button", { name: "Отклонить" });
    // Disabled until a reason is given.
    expect(submit).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Причина отклонения*"), "spam");
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() =>
      expect(registrationApi.reject).toHaveBeenCalledWith("req-1", {
        rejection_reason: "spam",
      }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Заявка отклонена"));
  });

  it("shows an error toast when reject fails", async () => {
    const user = userEvent.setup();
    registrationApi.reject.mockRejectedValue(new Error("nope"));
    registrationApi.list.mockResolvedValue(page([makeReq()]));
    renderWithProviders(<RegistrationPage />);

    await user.click(await screen.findByTitle("Отклонить"));
    await user.type(screen.getByPlaceholderText("Причина отклонения*"), "spam");
    await user.click(screen.getByRole("button", { name: "Отклонить" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось отклонить заявку"),
    );
  });

  it("closes the reject dialog via the cancel button", async () => {
    const user = userEvent.setup();
    registrationApi.list.mockResolvedValue(page([makeReq()]));
    renderWithProviders(<RegistrationPage />);

    await user.click(await screen.findByTitle("Отклонить"));
    await screen.findByText("Отклонить заявку — new@example.com");

    await user.click(screen.getByRole("button", { name: "Отмена" }));

    await waitFor(() =>
      expect(
        screen.queryByText("Отклонить заявку — new@example.com"),
      ).not.toBeInTheDocument(),
    );
    expect(registrationApi.reject).not.toHaveBeenCalled();
  });

  it("shows the empty state when there are no requests", async () => {
    registrationApi.list.mockResolvedValue(page([]));
    renderWithProviders(<RegistrationPage />);

    expect(await screen.findByText("Заявок нет.")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    let resolve!: (v: ReturnType<typeof page>) => void;
    registrationApi.list.mockReturnValue(new Promise((r) => (resolve = r)));
    const { container } = renderWithProviders(<RegistrationPage />);

    expect(container.querySelectorAll("table tbody tr").length).toBe(5);
    resolve(page([]));
  });

  it("changes the status filter", async () => {
    const user = userEvent.setup();
    registrationApi.list.mockResolvedValue(page([makeReq()]));
    renderWithProviders(<RegistrationPage />);

    await screen.findByText("new@example.com");
    await user.click(screen.getByRole("button", { name: "Одобренные" }));

    await waitFor(() =>
      expect(registrationApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "approved", offset: 0 }),
      ),
    );
  });

  it("paginates across pages", async () => {
    const user = userEvent.setup();
    registrationApi.list.mockResolvedValue(page([makeReq()], 40));
    renderWithProviders(<RegistrationPage />);

    await screen.findByText("new@example.com");
    expect(screen.getByText(/Стр\. 1 \/ 2/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Вперёд/ }));

    await waitFor(() =>
      expect(registrationApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 20 }),
      ),
    );
  });

  const statuses: [RegistrationStatus, string][] = [
    ["approved", "Одобрена"],
    ["rejected", "Отклонена"],
    ["cancelled", "Отменена"],
  ];
  it.each(statuses)("renders the %s status label", async (status, label) => {
    registrationApi.list.mockResolvedValue(page([makeReq({ status })]));
    renderWithProviders(<RegistrationPage />);

    expect(await screen.findByText(label)).toBeInTheDocument();
  });
});
