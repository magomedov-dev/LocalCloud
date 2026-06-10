import { createRef } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Separator } from "./separator";

describe("Separator", () => {
  it("отображает горизонтальный разделитель по умолчанию", () => {
    render(<Separator data-testid="sep" />);
    const sep = screen.getByTestId("sep");
    expect(sep).toHaveClass("h-px");
    expect(sep).toHaveClass("w-full");
    expect(sep).toHaveAttribute("data-orientation", "horizontal");
  });

  it("отображает вертикальный разделитель", () => {
    render(<Separator orientation="vertical" data-testid="sep" />);
    const sep = screen.getByTestId("sep");
    expect(sep).toHaveClass("w-px");
    expect(sep).toHaveClass("h-full");
    expect(sep).toHaveAttribute("data-orientation", "vertical");
  });

  it("пробрасывает className и ref", () => {
    const ref = createRef<HTMLDivElement>();
    render(<Separator ref={ref} className="extra" data-testid="sep" />);
    expect(ref.current).toBeInstanceOf(HTMLDivElement);
    expect(screen.getByTestId("sep")).toHaveClass("extra");
  });
});
