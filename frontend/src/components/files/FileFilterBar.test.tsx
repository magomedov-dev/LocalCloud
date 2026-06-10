import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileFilterBar } from "./FileFilterBar";

describe("FileFilterBar", () => {
  it("renders all filter buttons", () => {
    render(<FileFilterBar active="all" onChange={vi.fn()} />);
    for (const label of [
      "Все",
      "Папки",
      "Изображения",
      "Документы",
      "Видео",
      "Аудио",
      "Архивы",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("highlights the active filter", () => {
    render(<FileFilterBar active="image" onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Изображения" }).className).toContain(
      "bg-primary",
    );
    expect(screen.getByRole("button", { name: "Все" }).className).toContain("bg-muted");
  });

  it("calls onChange with selected filter value", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<FileFilterBar active="all" onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "Видео" }));
    expect(onChange).toHaveBeenCalledWith("video");
  });
});
