import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { NodeListItem } from "@/types/nodes";
import { renderWithProviders } from "@tests/utils";
import { SearchBar } from "@/components/layout/SearchBar";

const search = vi.hoisted(() => vi.fn());
const navigate = vi.hoisted(() => vi.fn());

vi.mock("@/api/nodes", () => ({
  nodesApi: { search: (...args: unknown[]) => search(...args) },
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigate };
});

function makeItem(over: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: "n1",
    owner_id: "o1",
    parent_id: null,
    name: "Документ.txt",
    node_type: "file",
    path: "/Документ.txt",
    ...over,
  } as NodeListItem;
}

describe("SearchBar", () => {
  beforeEach(() => {
    search.mockReset();
    navigate.mockReset();
  });

  it("рендерит поле поиска", () => {
    renderWithProviders(<SearchBar />);
    expect(screen.getByLabelText("Поиск файлов и папок")).toBeInTheDocument();
  });

  it("выполняет поиск (debounce) и показывает результаты", async () => {
    search.mockResolvedValue({ items: [makeItem({ name: "Отчёт.pdf", path: "/Отчёт.pdf" })] });
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    await u.type(screen.getByLabelText("Поиск файлов и папок"), "отч");

    expect(await screen.findByText("Отчёт.pdf", {}, { timeout: 2000 })).toBeInTheDocument();
    expect(search).toHaveBeenCalledWith("отч", { limit: 10 });
  });

  it("показывает «Ничего не найдено» для пустого результата", async () => {
    search.mockResolvedValue({ items: [] });
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    await u.type(screen.getByLabelText("Поиск файлов и папок"), "xyz");

    expect(await screen.findByText("Ничего не найдено", {}, { timeout: 2000 })).toBeInTheDocument();
  });

  it("переходит к родительской папке файла при выборе", async () => {
    search.mockResolvedValue({
      items: [makeItem({ id: "f1", parent_id: "p1", name: "Файл.txt", path: "/Файл.txt" })],
    });
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    await u.type(screen.getByLabelText("Поиск файлов и папок"), "файл");

    const option = await screen.findByText("Файл.txt", {}, { timeout: 2000 });
    await u.click(option);

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/files/folders/p1", { state: { selectId: "f1" } }),
    );
  });

  it("переходит к самой папке при выборе папки", async () => {
    search.mockResolvedValue({
      items: [
        makeItem({
          id: "d1",
          node_type: "folder",
          name: "Папка",
          path: "/Папка",
        }),
      ],
    });
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    await u.type(screen.getByLabelText("Поиск файлов и папок"), "папка");

    const option = await screen.findByText("Папка", {}, { timeout: 2000 });
    await u.click(option);

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/files/folders/d1", { state: undefined }),
    );
  });

  it("Ctrl+K фокусирует поле ввода", async () => {
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    const input = screen.getByLabelText("Поиск файлов и папок");
    expect(input).not.toHaveFocus();
    await u.keyboard("{Control>}k{/Control}");
    expect(input).toHaveFocus();
  });

  it("навигация стрелками и Enter выбирает результат", async () => {
    search.mockResolvedValue({
      items: [
        makeItem({ id: "a1", node_type: "folder", name: "Альфа", path: "/Альфа" }),
        makeItem({ id: "b2", node_type: "folder", name: "Бета", path: "/Бета" }),
      ],
    });
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    const input = screen.getByLabelText("Поиск файлов и папок");
    await u.type(input, "б");

    await screen.findByText("Бета", {}, { timeout: 2000 });

    // Вниз дважды -> второй элемент, затем вверх -> первый, Enter выбирает.
    await u.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}{Enter}");

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/files/folders/a1", { state: undefined }),
    );
  });

  it("Escape закрывает выпадающий список", async () => {
    search.mockResolvedValue({
      items: [makeItem({ node_type: "folder", name: "Гамма", path: "/Гамма" })],
    });
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    const input = screen.getByLabelText("Поиск файлов и папок");
    await u.type(input, "г");

    expect(await screen.findByText("Гамма", {}, { timeout: 2000 })).toBeInTheDocument();
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByText("Гамма")).not.toBeInTheDocument());
  });

  it("blur закрывает выпадающий список (без таймера)", async () => {
    search.mockResolvedValue({
      items: [makeItem({ node_type: "folder", name: "Дельта", path: "/Дельта" })],
    });
    const u = userEvent.setup();
    renderWithProviders(<SearchBar />);
    const input = screen.getByLabelText("Поиск файлов и папок");
    await u.type(input, "д");

    expect(await screen.findByText("Дельта", {}, { timeout: 2000 })).toBeInTheDocument();
    // Уводим фокус с поля — список закрывается сразу, без отложенного таймера.
    await u.tab();
    await waitFor(() => expect(screen.queryByText("Дельта")).not.toBeInTheDocument());
  });
});
