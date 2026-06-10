import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

import { Toaster } from "./sonner";

describe("Toaster (sonner)", () => {
  it("монтируется без ошибок", () => {
    const { container } = render(<Toaster />);
    // sonner рендерит секцию-обёртку для уведомлений.
    expect(container.querySelector("section")).not.toBeNull();
  });

  it("пробрасывает дополнительные props без ошибок", () => {
    const { container } = render(<Toaster position="top-center" richColors />);
    // Обёртка уведомлений присутствует независимо от переданных опций.
    expect(container.querySelector("section")).not.toBeNull();
  });
});
