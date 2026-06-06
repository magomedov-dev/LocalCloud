import { createRef } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Checkbox } from "@/components/ui/checkbox";

describe("Checkbox", () => {
  it("отображает чекбокс", () => {
    render(<Checkbox aria-label="cb" />);
    const cb = screen.getByRole("checkbox");
    expect(cb).toHaveAttribute("type", "checkbox");
    expect(cb).toHaveClass("accent-primary");
  });

  it("вызывает onCheckedChange при клике", async () => {
    const onCheckedChange = vi.fn();
    const user = userEvent.setup();
    render(<Checkbox aria-label="cb" onCheckedChange={onCheckedChange} />);
    await user.click(screen.getByRole("checkbox"));
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it("передаёт false при снятии отметки", async () => {
    const onCheckedChange = vi.fn();
    const user = userEvent.setup();
    render(<Checkbox aria-label="cb" defaultChecked onCheckedChange={onCheckedChange} />);
    await user.click(screen.getByRole("checkbox"));
    expect(onCheckedChange).toHaveBeenLastCalledWith(false);
  });

  it("пробрасывает className и ref", () => {
    const ref = createRef<HTMLInputElement>();
    render(<Checkbox ref={ref} className="extra" aria-label="cb" />);
    expect(ref.current).toBeInstanceOf(HTMLInputElement);
    expect(screen.getByRole("checkbox")).toHaveClass("extra");
  });

  it("не падает без onCheckedChange", async () => {
    const user = userEvent.setup();
    render(<Checkbox aria-label="cb" />);
    await user.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("checkbox")).toBeChecked();
  });
});
