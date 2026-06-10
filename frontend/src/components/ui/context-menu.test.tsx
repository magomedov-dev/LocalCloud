import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuCheckboxItem,
  ContextMenuRadioItem,
  ContextMenuRadioGroup,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuGroup,
} from "./context-menu";

function renderMenu() {
  return render(
    <ContextMenu>
      <ContextMenuTrigger>Кликни ПКМ</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuLabel>Метка</ContextMenuLabel>
        <ContextMenuSeparator />
        <ContextMenuGroup>
          <ContextMenuItem>Скопировать</ContextMenuItem>
          <ContextMenuItem inset>С отступом</ContextMenuItem>
        </ContextMenuGroup>
        <ContextMenuCheckboxItem checked>Чек</ContextMenuCheckboxItem>
        <ContextMenuRadioGroup value="a">
          <ContextMenuRadioItem value="a">Опция A</ContextMenuRadioItem>
        </ContextMenuRadioGroup>
      </ContextMenuContent>
    </ContextMenu>,
  );
}

describe("ContextMenu", () => {
  it("открывает меню по правому клику и отображает пункты", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.pointer({ keys: "[MouseRight]", target: screen.getByText("Кликни ПКМ") });

    expect(screen.getByText("Метка")).toBeInTheDocument();
    expect(screen.getByText("Скопировать")).toBeInTheDocument();
    expect(screen.getByText("С отступом")).toHaveClass("pl-8");
    expect(screen.getByText("Чек")).toBeInTheDocument();
    expect(screen.getByText("Опция A")).toBeInTheDocument();
  });

  it("отмеченный checkbox-пункт имеет state=checked", async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.pointer({ keys: "[MouseRight]", target: screen.getByText("Кликни ПКМ") });
    const item = screen.getByText("Чек").closest("[role='menuitemcheckbox']");
    expect(item).toHaveAttribute("data-state", "checked");
  });
});
