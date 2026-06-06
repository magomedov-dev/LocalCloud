import { createRef } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
  BreadcrumbEllipsis,
} from "@/components/ui/breadcrumb";

describe("Breadcrumb", () => {
  it("отображает навигацию с элементами", () => {
    render(
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/">Главная</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Текущая</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>,
    );
    expect(screen.getByRole("navigation", { name: "breadcrumb" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Главная" })).toHaveAttribute("href", "/");
    const page = screen.getByText("Текущая");
    expect(page).toHaveAttribute("aria-current", "page");
  });

  it("отображает разделитель по умолчанию (иконка)", () => {
    render(<BreadcrumbSeparator data-testid="sep" />);
    const sep = screen.getByTestId("sep");
    expect(sep).toHaveAttribute("aria-hidden", "true");
    expect(sep.querySelector("svg")).not.toBeNull();
  });

  it("отображает кастомный разделитель", () => {
    render(<BreadcrumbSeparator>/</BreadcrumbSeparator>);
    expect(screen.getByText("/")).toBeInTheDocument();
  });

  it("отображает ellipsis", () => {
    render(<BreadcrumbEllipsis data-testid="el" />);
    expect(screen.getByTestId("el")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("More")).toBeInTheDocument();
  });

  it("рендерит ссылку через asChild", () => {
    render(
      <BreadcrumbLink asChild>
        <button type="button">кнопка</button>
      </BreadcrumbLink>,
    );
    expect(screen.getByRole("button", { name: "кнопка" })).toHaveClass("transition-colors");
  });

  it("пробрасывает ref на nav", () => {
    const ref = createRef<HTMLElement>();
    render(<Breadcrumb ref={ref} />);
    expect(ref.current?.tagName).toBe("NAV");
  });
});
