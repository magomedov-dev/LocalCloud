import { createRef } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("отображает содержимое как кнопку", () => {
    render(<Button>Нажми</Button>);
    const btn = screen.getByRole("button", { name: "Нажми" });
    expect(btn.tagName).toBe("BUTTON");
  });

  it("применяет variant и size", () => {
    render(
      <Button variant="outline" size="sm">
        о
      </Button>,
    );
    const btn = screen.getByRole("button");
    expect(btn).toHaveClass("border-input");
    expect(btn).toHaveClass("h-9");
  });

  it("пробрасывает className и ref", () => {
    const ref = createRef<HTMLButtonElement>();
    render(
      <Button ref={ref} className="extra">
        x
      </Button>,
    );
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
    expect(screen.getByRole("button")).toHaveClass("extra");
  });

  it("вызывает onClick", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={onClick}>click</Button>);
    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("не вызывает onClick в состоянии disabled", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <Button disabled onClick={onClick}>
        click
      </Button>,
    );
    await user.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("рендерит дочерний элемент при asChild", () => {
    render(
      <Button asChild>
        <a href="/home">ссылка</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "ссылка" });
    expect(link).toHaveAttribute("href", "/home");
    // Классы варианта применяются к дочернему элементу.
    expect(link).toHaveClass("bg-primary");
  });
});
