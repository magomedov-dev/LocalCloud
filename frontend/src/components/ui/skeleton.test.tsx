import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Skeleton } from "./skeleton";

describe("Skeleton", () => {
  it("отображает блок с анимацией пульсации", () => {
    render(<Skeleton data-testid="sk" />);
    const el = screen.getByTestId("sk");
    expect(el).toHaveClass("animate-pulse");
    expect(el).toHaveClass("rounded-md");
  });

  it("пробрасывает className и атрибуты", () => {
    render(<Skeleton className="h-8 w-8" data-testid="sk" />);
    expect(screen.getByTestId("sk")).toHaveClass("h-8");
  });
});
