import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FolderColorDialog } from "./FolderColorDialog";
import { FOLDER_COLORS } from "./folderColors";

describe("FolderColorDialog", () => {
  function setup(currentColor: string | null = null) {
    const onOpenChange = vi.fn();
    const onColorChange = vi.fn();
    render(
      <FolderColorDialog
        open
        onOpenChange={onOpenChange}
        nodeId="n1"
        currentColor={currentColor}
        onColorChange={onColorChange}
      />,
    );
    return { onOpenChange, onColorChange };
  }

  it("отображает заголовок и кнопки всех цветов", () => {
    setup();
    expect(screen.getByText("Цвет папки")).toBeInTheDocument();
    for (const c of FOLDER_COLORS) {
      expect(screen.getByTitle(c.label)).toBeInTheDocument();
    }
  });

  it("ничего не рендерит в закрытом состоянии", () => {
    render(
      <FolderColorDialog
        open={false}
        onOpenChange={vi.fn()}
        nodeId="n1"
        currentColor={null}
        onColorChange={vi.fn()}
      />,
    );
    expect(screen.queryByText("Цвет папки")).not.toBeInTheDocument();
  });

  it("выбирает цвет и закрывает диалог", async () => {
    const user = userEvent.setup();
    const { onColorChange, onOpenChange } = setup();
    await user.click(screen.getByTitle(FOLDER_COLORS[0].label));
    expect(onColorChange).toHaveBeenCalledWith(FOLDER_COLORS[0].value);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("сбрасывает цвет при нажатии «Сбросить»", async () => {
    const user = userEvent.setup();
    const { onColorChange, onOpenChange } = setup("#eab308");
    await user.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(onColorChange).toHaveBeenCalledWith(null);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("подсвечивает текущий выбранный цвет кольцом", () => {
    setup(FOLDER_COLORS[1].value);
    expect(screen.getByTitle(FOLDER_COLORS[1].label).className).toContain("ring-2");
    expect(screen.getByTitle(FOLDER_COLORS[0].label).className).not.toContain("ring-2");
  });
});
