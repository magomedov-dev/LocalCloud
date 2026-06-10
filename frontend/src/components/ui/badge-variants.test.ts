import { describe, it, expect } from "vitest";

import { badgeVariants } from "./badge-variants";

describe("badgeVariants", () => {
  it("применяет базовые классы и вариант по умолчанию", () => {
    const result = badgeVariants();
    expect(result).toContain("inline-flex");
    expect(result).toContain("rounded-full");
    // По умолчанию variant === "default".
    expect(result).toContain("bg-primary");
    expect(result).toContain("text-primary-foreground");
  });

  it("применяет классы варианта secondary", () => {
    const result = badgeVariants({ variant: "secondary" });
    expect(result).toContain("bg-secondary");
    expect(result).toContain("text-secondary-foreground");
  });

  it("применяет классы варианта destructive", () => {
    const result = badgeVariants({ variant: "destructive" });
    expect(result).toContain("bg-destructive");
    expect(result).toContain("text-destructive-foreground");
  });

  it("применяет классы варианта outline", () => {
    const result = badgeVariants({ variant: "outline" });
    expect(result).toContain("text-foreground");
    expect(result).not.toContain("bg-primary");
  });
});
