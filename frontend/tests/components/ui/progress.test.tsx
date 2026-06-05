import { createRef } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Progress } from "@/components/ui/progress";

describe("Progress", () => {
  it("отображает индикатор прогресса", () => {
    render(<Progress value={40} data-testid="progress" />);
    const root = screen.getByTestId("progress");
    expect(root).toHaveAttribute("role", "progressbar");
    expect(root).toHaveClass("rounded-full");
  });

  it("сдвигает индикатор согласно value", () => {
    render(<Progress value={25} data-testid="progress" />);
    const indicator = screen.getByTestId("progress").querySelector("div");
    expect(indicator).toHaveStyle({ transform: "translateX(-75%)" });
  });

  it("по умолчанию (без value) сдвигает на 100%", () => {
    render(<Progress data-testid="progress" />);
    const indicator = screen.getByTestId("progress").querySelector("div");
    expect(indicator).toHaveStyle({ transform: "translateX(-100%)" });
  });

  it("пробрасывает className и ref", () => {
    const ref = createRef<HTMLDivElement>();
    render(<Progress ref={ref} value={10} className="extra" data-testid="progress" />);
    expect(ref.current).toBeInstanceOf(HTMLDivElement);
    expect(screen.getByTestId("progress")).toHaveClass("extra");
  });
});
