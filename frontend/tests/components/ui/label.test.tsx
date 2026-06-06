import { createRef } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Label } from "@/components/ui/label";

describe("Label", () => {
  it("отображает текст метки", () => {
    render(<Label>Метка</Label>);
    expect(screen.getByText("Метка")).toBeInTheDocument();
  });

  it("применяет базовые классы и className", () => {
    render(
      <Label className="extra" data-testid="label">
        м
      </Label>,
    );
    const label = screen.getByTestId("label");
    expect(label).toHaveClass("text-sm");
    expect(label).toHaveClass("extra");
  });

  it("связывается с полем через htmlFor", () => {
    render(<Label htmlFor="field">Поле</Label>);
    expect(screen.getByText("Поле")).toHaveAttribute("for", "field");
  });

  it("пробрасывает ref", () => {
    const ref = createRef<HTMLLabelElement>();
    render(<Label ref={ref}>l</Label>);
    expect(ref.current).toBeInstanceOf(HTMLLabelElement);
  });
});
