import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DropZone } from "@/components/files/DropZone";

function makeFile(name: string, size: number): File {
  const f = new File(["x"], name, { type: "text/plain" });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

function dataTransfer({
  items = [],
  files = [],
}: {
  items?: { kind: string }[];
  files?: File[];
}) {
  return {
    items,
    files,
    dropEffect: "",
    getData: vi.fn(),
    setData: vi.fn(),
  };
}

describe("DropZone", () => {
  it("renders children", () => {
    render(
      <DropZone onDrop={vi.fn()}>
        <div>child</div>
      </DropZone>,
    );
    expect(screen.getByText("child")).toBeInTheDocument();
  });

  it("shows overlay on drag enter with files", () => {
    render(
      <DropZone onDrop={vi.fn()}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    fireEvent.dragEnter(zone, { dataTransfer: dataTransfer({ items: [{ kind: "file" }] }) });
    expect(screen.getByText("Отпустите файлы для загрузки")).toBeInTheDocument();
  });

  it("does not show overlay when drag has no files", () => {
    render(
      <DropZone onDrop={vi.fn()}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    fireEvent.dragEnter(zone, { dataTransfer: dataTransfer({ items: [{ kind: "string" }] }) });
    expect(screen.queryByText("Отпустите файлы для загрузки")).not.toBeInTheDocument();
  });

  it("hides overlay when drag fully leaves", () => {
    render(
      <DropZone onDrop={vi.fn()}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    fireEvent.dragEnter(zone, { dataTransfer: dataTransfer({ items: [{ kind: "file" }] }) });
    expect(screen.getByText("Отпустите файлы для загрузки")).toBeInTheDocument();
    fireEvent.dragLeave(zone, { dataTransfer: dataTransfer({ items: [{ kind: "file" }] }) });
    expect(screen.queryByText("Отпустите файлы для загрузки")).not.toBeInTheDocument();
  });

  it("keeps overlay when nested drag leaves but counter > 0", () => {
    render(
      <DropZone onDrop={vi.fn()}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    fireEvent.dragEnter(zone, { dataTransfer: dataTransfer({ items: [{ kind: "file" }] }) });
    fireEvent.dragEnter(zone, { dataTransfer: dataTransfer({ items: [{ kind: "file" }] }) });
    fireEvent.dragLeave(zone, { dataTransfer: dataTransfer({ items: [{ kind: "file" }] }) });
    expect(screen.getByText("Отпустите файлы для загрузки")).toBeInTheDocument();
  });

  it("sets copy dropEffect on drag over", () => {
    render(
      <DropZone onDrop={vi.fn()}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    const dt = dataTransfer({});
    fireEvent.dragOver(zone, { dataTransfer: dt });
    expect(dt.dropEffect).toBe("copy");
  });

  it("calls onDrop with non-empty files on drop", () => {
    const onDrop = vi.fn();
    render(
      <DropZone onDrop={onDrop}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    const files = [makeFile("a.txt", 5), makeFile("empty.txt", 0)];
    fireEvent.drop(zone, { dataTransfer: dataTransfer({ files }) });
    expect(onDrop).toHaveBeenCalledTimes(1);
    expect(onDrop.mock.calls[0][0]).toHaveLength(1);
    expect(onDrop.mock.calls[0][0][0].name).toBe("a.txt");
  });

  it("does not call onDrop when only empty files", () => {
    const onDrop = vi.fn();
    render(
      <DropZone onDrop={onDrop}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    fireEvent.drop(zone, { dataTransfer: dataTransfer({ files: [makeFile("e.txt", 0)] }) });
    expect(onDrop).not.toHaveBeenCalled();
  });

  it("does not call onDrop when disabled", () => {
    const onDrop = vi.fn();
    render(
      <DropZone onDrop={onDrop} disabled>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    fireEvent.drop(zone, { dataTransfer: dataTransfer({ files: [makeFile("a.txt", 5)] }) });
    expect(onDrop).not.toHaveBeenCalled();
  });

  it("hides overlay after drop", () => {
    render(
      <DropZone onDrop={vi.fn()}>
        <div>child</div>
      </DropZone>,
    );
    const zone = screen.getByText("child").parentElement!;
    fireEvent.dragEnter(zone, { dataTransfer: dataTransfer({ items: [{ kind: "file" }] }) });
    fireEvent.drop(zone, { dataTransfer: dataTransfer({ files: [] }) });
    expect(screen.queryByText("Отпустите файлы для загрузки")).not.toBeInTheDocument();
  });
});
