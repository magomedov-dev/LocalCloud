import { describe, it, expect } from "vitest";

import { buttonVariants } from "@/components/ui/button-variants";

describe("buttonVariants", () => {
  it("применяет базовые классы и значения по умолчанию", () => {
    const result = buttonVariants();
    expect(result).toContain("inline-flex");
    expect(result).toContain("rounded-md");
    // variant default + size default.
    expect(result).toContain("bg-primary");
    expect(result).toContain("h-10");
    expect(result).toContain("px-4");
  });

  it.each([
    ["default", "bg-primary"],
    ["destructive", "bg-destructive"],
    ["outline", "border-input"],
    ["secondary", "bg-secondary"],
    ["ghost", "hover:bg-accent"],
    ["link", "underline-offset-4"],
  ] as const)("применяет классы варианта %s", (variant, token) => {
    expect(buttonVariants({ variant })).toContain(token);
  });

  it.each([
    ["default", "h-10"],
    ["sm", "h-9"],
    ["lg", "h-11"],
    ["icon", "w-10"],
  ] as const)("применяет классы размера %s", (size, token) => {
    expect(buttonVariants({ size })).toContain(token);
  });

  it("комбинирует variant, size и дополнительный className", () => {
    const result = buttonVariants({ variant: "outline", size: "lg", className: "my-custom" });
    expect(result).toContain("border-input");
    expect(result).toContain("h-11");
    expect(result).toContain("my-custom");
  });
});
