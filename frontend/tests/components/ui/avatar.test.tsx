import { createRef } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";

describe("Avatar", () => {
  it("отображает контейнер аватара с fallback", () => {
    render(
      <Avatar data-testid="avatar">
        <AvatarImage src="/u.png" alt="user" />
        <AvatarFallback>AB</AvatarFallback>
      </Avatar>,
    );
    const root = screen.getByTestId("avatar");
    expect(root).toHaveClass("rounded-full");
    // В jsdom изображение не загружается, поэтому показывается fallback.
    expect(screen.getByText("AB")).toBeInTheDocument();
  });

  it("применяет классы fallback", () => {
    render(
      <Avatar>
        <AvatarFallback data-testid="fb">CD</AvatarFallback>
      </Avatar>,
    );
    expect(screen.getByTestId("fb")).toHaveClass("bg-muted");
  });

  it("пробрасывает ref и className на корне", () => {
    const ref = createRef<HTMLSpanElement>();
    render(<Avatar ref={ref} className="extra" data-testid="avatar" />);
    expect(ref.current).not.toBeNull();
    expect(screen.getByTestId("avatar")).toHaveClass("extra");
  });
});
