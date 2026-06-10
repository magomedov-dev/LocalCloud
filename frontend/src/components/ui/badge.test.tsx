import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Badge } from "./badge";

describe("Badge", () => {
  it("отображает содержимое", () => {
    render(<Badge>Новый</Badge>);
    expect(screen.getByText("Новый")).toBeInTheDocument();
  });

  it("применяет вариант по умолчанию", () => {
    render(<Badge>def</Badge>);
    expect(screen.getByText("def")).toHaveClass("bg-primary");
  });

  it("применяет переданный вариант", () => {
    render(<Badge variant="destructive">err</Badge>);
    expect(screen.getByText("err")).toHaveClass("bg-destructive");
  });

  it("пробрасывает className и HTML-атрибуты", () => {
    render(
      <Badge className="extra" data-testid="badge">
        x
      </Badge>,
    );
    expect(screen.getByTestId("badge")).toHaveClass("extra");
  });
});
