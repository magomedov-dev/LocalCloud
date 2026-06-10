import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
  SheetClose,
} from "./sheet";

function renderSheet(
  rootProps?: Partial<React.ComponentProps<typeof Sheet>>,
  side?: React.ComponentProps<typeof SheetContent>["side"],
) {
  return render(
    <Sheet {...rootProps}>
      <SheetTrigger>Открыть</SheetTrigger>
      <SheetContent side={side} aria-describedby={undefined}>
        <SheetHeader>
          <SheetTitle>Заголовок панели</SheetTitle>
          <SheetDescription>Описание панели</SheetDescription>
        </SheetHeader>
        <SheetFooter>
          <SheetClose>Закрыть</SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>,
  );
}

describe("Sheet", () => {
  it("отображает содержимое при defaultOpen", () => {
    renderSheet({ defaultOpen: true });
    expect(screen.getByText("Заголовок панели")).toBeInTheDocument();
    expect(screen.getByText("Описание панели")).toBeInTheDocument();
  });

  it("открывается по клику на trigger", async () => {
    const user = userEvent.setup();
    renderSheet();
    expect(screen.queryByText("Заголовок панели")).not.toBeInTheDocument();
    await user.click(screen.getByText("Открыть"));
    expect(screen.getByText("Заголовок панели")).toBeInTheDocument();
  });

  it("применяет классы стороны left", () => {
    renderSheet({ defaultOpen: true }, "left");
    expect(screen.getByRole("dialog")).toHaveClass("left-0");
  });

  it("применяет классы стороны right по умолчанию", () => {
    renderSheet({ defaultOpen: true });
    expect(screen.getByRole("dialog")).toHaveClass("right-0");
  });

  it("вызывает onOpenChange при закрытии", async () => {
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    renderSheet({ defaultOpen: true, onOpenChange });
    await user.click(screen.getByText("Закрыть"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
