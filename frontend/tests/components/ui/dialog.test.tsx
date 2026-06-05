import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog";

function renderDialog(props?: Partial<React.ComponentProps<typeof Dialog>>) {
  return render(
    <Dialog {...props}>
      <DialogTrigger>Открыть</DialogTrigger>
      <DialogContent hasDescription>
        <DialogHeader>
          <DialogTitle>Заголовок диалога</DialogTitle>
          <DialogDescription>Описание диалога</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose>Закрыть</DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>,
  );
}

describe("Dialog", () => {
  it("отображает содержимое при defaultOpen", () => {
    renderDialog({ defaultOpen: true });
    expect(screen.getByText("Заголовок диалога")).toBeInTheDocument();
    expect(screen.getByText("Описание диалога")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("открывается по клику на trigger", async () => {
    const user = userEvent.setup();
    renderDialog();
    expect(screen.queryByText("Заголовок диалога")).not.toBeInTheDocument();
    await user.click(screen.getByText("Открыть"));
    expect(screen.getByText("Заголовок диалога")).toBeInTheDocument();
  });

  it("вызывает onOpenChange при закрытии", async () => {
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    renderDialog({ defaultOpen: true, onOpenChange });
    await user.click(screen.getByText("Закрыть"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("содержит встроенную кнопку закрытия", () => {
    renderDialog({ defaultOpen: true });
    expect(screen.getByText("Close")).toBeInTheDocument();
  });
});
