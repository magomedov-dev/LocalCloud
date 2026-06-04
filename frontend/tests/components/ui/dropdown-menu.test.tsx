import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioItem,
  DropdownMenuRadioGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuGroup,
} from "@/components/ui/dropdown-menu";

describe("DropdownMenu", () => {
  it("отображает содержимое в открытом состоянии", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger>Меню</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuLabel>Действия</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem>
              Профиль
              <DropdownMenuShortcut>⌘P</DropdownMenuShortcut>
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuCheckboxItem checked>Показывать панель</DropdownMenuCheckboxItem>
          <DropdownMenuRadioGroup value="a">
            <DropdownMenuRadioItem value="a">Опция A</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    expect(screen.getByText("Действия")).toBeInTheDocument();
    expect(screen.getByText("Профиль")).toBeInTheDocument();
    expect(screen.getByText("⌘P")).toBeInTheDocument();
    expect(screen.getByText("Показывать панель")).toBeInTheDocument();
    expect(screen.getByText("Опция A")).toBeInTheDocument();
  });

  it("применяет inset-отступ к пункту", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger>m</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem inset>С отступом</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    expect(screen.getByText("С отступом")).toHaveClass("pl-8");
  });

  it("отмеченный checkbox-пункт показывает индикатор", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger>m</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuCheckboxItem checked>Чек</DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    const item = screen.getByText("Чек").closest("[role='menuitemcheckbox']");
    expect(item).toHaveAttribute("data-state", "checked");
  });
});
