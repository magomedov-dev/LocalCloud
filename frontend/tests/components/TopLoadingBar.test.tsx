import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { TopLoadingBar } from "@/components/TopLoadingBar";

describe("TopLoadingBar", () => {
  it("ничего не рендерит, когда не активна", () => {
    const { container } = render(<TopLoadingBar active={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("рендерит индикатор, когда активна", () => {
    const { container } = render(<TopLoadingBar active />);
    expect(container.querySelector(".bg-primary")).not.toBeNull();
  });
});
