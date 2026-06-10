import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { ShareDialog } from "./ShareDialog";
import { publicLinksApi } from "@/api/public-links";
import type { PublicLinkListItem } from "@/types/public-links";

vi.mock("@/api/public-links", () => ({
  publicLinksApi: {
    listForNode: vi.fn(),
    create: vi.fn(),
    revoke: vi.fn(),
    update: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  }),
}));

import { toast } from "sonner";

const mockList = vi.mocked(publicLinksApi.listForNode);
const mockCreate = vi.mocked(publicLinksApi.create);
const mockRevoke = vi.mocked(publicLinksApi.revoke);
const mockUpdate = vi.mocked(publicLinksApi.update);

function link(overrides: Partial<PublicLinkListItem> = {}): PublicLinkListItem {
  return {
    id: "l1",
    node_id: "n1",
    token: "tok123",
    permission_type: "download",
    status: "active",
    expires_at: null,
    download_count: 0,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    has_password: false,
    node: null,
    ...overrides,
  };
}

function renderDialog() {
  const onOpenChange = vi.fn();
  const utils = renderWithProviders(
    <ShareDialog open onOpenChange={onOpenChange} nodeId="n1" nodeName="файл.txt" />,
  );
  return { onOpenChange, ...utils };
}

describe("ShareDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    });
  });

  it("показывает имя узла и форму создания при отсутствии активной ссылки", async () => {
    mockList.mockResolvedValue({ items: [] } as never);
    renderDialog();
    expect(screen.getByText("Публичная ссылка")).toBeInTheDocument();
    expect(screen.getByText("файл.txt")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Создать ссылку/ })).toBeInTheDocument();
  });

  it("создаёт ссылку с паролем: вызывает API и показывает success", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [] } as never);
    mockCreate.mockResolvedValue({} as never);
    renderDialog();

    const pwd = await screen.findByLabelText(/Пароль/);
    await user.type(pwd, "secret");
    await user.click(screen.getByRole("button", { name: /Создать ссылку/ }));

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        node_id: "n1",
        permission_type: "download",
        password: "secret",
      }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Ссылка создана"));
  });

  it("создаёт ссылку без пароля (password=null)", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [] } as never);
    mockCreate.mockResolvedValue({} as never);
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /Создать ссылку/ }));
    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        node_id: "n1",
        permission_type: "download",
        password: null,
      }),
    );
  });

  it("показывает toast ошибки при неудачном создании", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [] } as never);
    mockCreate.mockRejectedValue(new Error("fail"));
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /Создать ссылку/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Не удалось создать ссылку"));
  });

  it("показывает активную ссылку и копирует URL в буфер", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [link()] } as never);
    renderDialog();

    expect(await screen.findByText("Ссылка активна")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/\/share\/tok123$/)).toBeInTheDocument();

    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    await user.click(screen.getByTitle("Скопировать ссылку"));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("/share/tok123"));
  });

  it("отзывает активную ссылку", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [link()] } as never);
    mockRevoke.mockResolvedValue({} as never);
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /Отозвать ссылку/ }));
    await waitFor(() => expect(mockRevoke).toHaveBeenCalledWith("l1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Ссылка отозвана"));
  });

  it("показывает ошибку при неудачном отзыве", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [link()] } as never);
    mockRevoke.mockRejectedValue(new Error("fail"));
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /Отозвать ссылку/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Не удалось отозвать ссылку"));
  });

  it("задаёт пароль на активной ссылке", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [link()] } as never);
    mockUpdate.mockResolvedValue({} as never);
    renderDialog();

    await screen.findByText("Ссылка активна");
    const input = screen.getByPlaceholderText("Задать пароль");
    await user.type(input, "newpass");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("l1", { password: "newpass" }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Пароль обновлён"));
  });

  it("удаляет пароль с защищённой ссылки", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [link({ has_password: true })] } as never);
    mockUpdate.mockResolvedValue({} as never);
    renderDialog();

    await screen.findByText("Ссылка активна");
    expect(screen.getByText("Под паролем")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Убрать пароль" }));
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("l1", { clear_password: true }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Пароль удалён"));
  });

  it("показывает ошибку при неудачном обновлении пароля", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValue({ items: [link()] } as never);
    mockUpdate.mockRejectedValue(new Error("fail"));
    renderDialog();

    await screen.findByText("Ссылка активна");
    await user.type(screen.getByPlaceholderText("Задать пароль"), "x");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось обновить пароль ссылки"),
    );
  });

  it("показывает skeleton во время загрузки", () => {
    mockList.mockReturnValue(new Promise(() => {}) as never);
    renderDialog();
    expect(screen.queryByText("Ссылка активна")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Создать ссылку/ })).not.toBeInTheDocument();
  });
});
