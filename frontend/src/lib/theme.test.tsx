import { act, render, screen, waitFor } from "@testing-library/react";
import { useTheme } from "next-themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "./theme";

function ThemeConsumer() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolvedTheme}</span>
      <button onClick={() => setTheme("dark")}>dark</button>
      <button onClick={() => setTheme("light")}>light</button>
    </div>
  );
}

/**
 * jsdom в этом окружении не предоставляет рабочий `window.localStorage`
 * (Node experimental webstorage перекрывает его). Ставим Map-backed Storage-стаб,
 * который next-themes использует через `window.localStorage`.
 */
function installLocalStorage(): Storage {
  const map = new Map<string, string>();
  const stub: Storage = {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    setItem: (k: string, v: string) => {
      map.set(k, String(v));
    },
    removeItem: (k: string) => {
      map.delete(k);
    },
    key: (i: number) => Array.from(map.keys())[i] ?? null,
  };
  Object.defineProperty(window, "localStorage", {
    value: stub,
    configurable: true,
    writable: true,
  });
  return stub;
}

function setMatchMedia(prefersDark: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("dark") ? prefersDark : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    installLocalStorage();
    document.documentElement.className = "";
    setMatchMedia(false);
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
  });

  it("рендерит дочерние элементы", () => {
    render(
      <ThemeProvider>
        <p>child-content</p>
      </ThemeProvider>,
    );
    expect(screen.getByText("child-content")).toBeInTheDocument();
  });

  it("по умолчанию использует системную тему", async () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("theme")).toHaveTextContent("system");
    });
  });

  it("читает системное предпочтение dark через matchMedia", async () => {
    setMatchMedia(true);
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("resolved")).toHaveTextContent("dark");
    });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("переключает тему и навешивает класс на documentElement", async () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    await act(async () => {
      screen.getByText("dark").click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    });
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    await act(async () => {
      screen.getByText("light").click();
    });
    await waitFor(() => {
      expect(document.documentElement.classList.contains("light")).toBe(true);
    });
  });

  it("сохраняет выбранную тему в localStorage по ключу theme", async () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );

    await act(async () => {
      screen.getByText("dark").click();
    });

    await waitFor(() => {
      expect(window.localStorage.getItem("theme")).toBe("dark");
    });
  });

  it("восстанавливает сохранённую тему из localStorage", async () => {
    window.localStorage.setItem("theme", "dark");
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    });
  });
});
