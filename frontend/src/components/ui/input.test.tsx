import { createRef } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Input } from "./input";

describe("Input", () => {
  it("отображает input с базовыми классами", () => {
    render(<Input placeholder="Имя" />);
    const input = screen.getByPlaceholderText("Имя");
    expect(input.tagName).toBe("INPUT");
    expect(input).toHaveClass("rounded-md");
  });

  it("применяет тип и className", () => {
    render(<Input type="email" className="extra" placeholder="email" />);
    const input = screen.getByPlaceholderText("email");
    expect(input).toHaveAttribute("type", "email");
    expect(input).toHaveClass("extra");
  });

  it("пробрасывает ref", () => {
    const ref = createRef<HTMLInputElement>();
    render(<Input ref={ref} />);
    expect(ref.current).toBeInstanceOf(HTMLInputElement);
  });

  it("обрабатывает ввод текста", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Input onChange={onChange} placeholder="p" />);
    const input = screen.getByPlaceholderText("p");
    await user.type(input, "abc");
    expect(input).toHaveValue("abc");
    expect(onChange).toHaveBeenCalled();
  });

  it("не позволяет ввод в состоянии disabled", async () => {
    const user = userEvent.setup();
    render(<Input disabled placeholder="p" />);
    const input = screen.getByPlaceholderText("p");
    await user.type(input, "abc");
    expect(input).toHaveValue("");
  });
});
