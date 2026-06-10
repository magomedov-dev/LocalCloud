import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeToggle } from "@/components/layout/ThemeToggle";

const setTheme = vi.fn();
let currentTheme: string | undefined = "system";

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: currentTheme, setTheme }),
}));

function renderToggle() {
  return render(
    <TooltipProvider>
      <ThemeToggle />
    </TooltipProvider>,
  );
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    setTheme.mockClear();
    currentTheme = "system";
  });

  it("показывает системную иконку и подпись по умолчанию", () => {
    renderToggle();
    expect(screen.getByRole("button", { name: "Системная тема" })).toBeInTheDocument();
  });

  it("из system переключает на light", async () => {
    currentTheme = "system";
    renderToggle();
    await userEvent.click(screen.getByRole("button", { name: "Системная тема" }));
    expect(setTheme).toHaveBeenCalledWith("light");
  });

  it("из light переключает на dark", async () => {
    currentTheme = "light";
    renderToggle();
    await userEvent.click(screen.getByRole("button", { name: "Светлая тема" }));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("из dark переключает на system (циклически)", async () => {
    currentTheme = "dark";
    renderToggle();
    await userEvent.click(screen.getByRole("button", { name: "Тёмная тема" }));
    expect(setTheme).toHaveBeenCalledWith("system");
  });

  it("неизвестная тема трактуется как system", () => {
    currentTheme = "something-weird";
    renderToggle();
    expect(screen.getByRole("button", { name: "Системная тема" })).toBeInTheDocument();
  });

  it("undefined тема трактуется как system", () => {
    currentTheme = undefined;
    renderToggle();
    expect(screen.getByRole("button", { name: "Системная тема" })).toBeInTheDocument();
  });
});
