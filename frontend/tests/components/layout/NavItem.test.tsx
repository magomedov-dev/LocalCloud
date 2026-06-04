import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Files } from "lucide-react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NavItem } from "@/components/layout/NavItem";

function renderNav(props: Partial<{ collapsed: boolean }> & { route?: string } = {}) {
  const { route = "/", collapsed = false } = props;
  return render(
    <MemoryRouter initialEntries={[route]}>
      <TooltipProvider>
        <NavItem to="/files" icon={Files} label="Файлы" collapsed={collapsed} />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

describe("NavItem", () => {
  it("отображает подпись и ссылку в развёрнутом виде", () => {
    renderNav({ route: "/other" });
    const link = screen.getByRole("link", { name: "Файлы" });
    expect(link).toHaveAttribute("href", "/files");
    expect(screen.getByText("Файлы")).toBeInTheDocument();
  });

  it("помечает ссылку активной для текущего маршрута", () => {
    renderNav({ route: "/files" });
    expect(screen.getByRole("link", { name: "Файлы" })).toHaveAttribute("aria-current", "page");
  });

  it("не помечает ссылку активной вне маршрута", () => {
    renderNav({ route: "/other" });
    expect(screen.getByRole("link", { name: "Файлы" })).not.toHaveAttribute("aria-current");
  });

  it("скрывает подпись в свёрнутом виде, сохраняя ссылку", () => {
    renderNav({ collapsed: true, route: "/other" });
    expect(screen.queryByText("Файлы")).not.toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/files");
  });
});
