import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

vi.mock("lucide-react", () => {
  const make = (name: string) => {
    const C = (props: Record<string, unknown>) => (
      <svg data-icon={name} className={props.className as string} style={props.style as object} />
    );
    return C;
  };
  return {
    Folder: make("Folder"),
    File: make("File"),
    FileImage: make("FileImage"),
    FileVideo: make("FileVideo"),
    FileAudio: make("FileAudio"),
    FileText: make("FileText"),
    FileArchive: make("FileArchive"),
    FileCode: make("FileCode"),
    FileSpreadsheet: make("FileSpreadsheet"),
  };
});

import { FileIcon } from "./FileIcon";

function iconName(container: HTMLElement): string | null {
  return container.querySelector("svg")?.getAttribute("data-icon") ?? null;
}

describe("FileIcon", () => {
  it("renders Folder with default yellow color when no color given", () => {
    const { container } = render(<FileIcon nodeType="folder" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("data-icon")).toBe("Folder");
    expect(svg.getAttribute("class")).toContain("text-yellow-500");
  });

  it("renders Folder with custom color (no yellow class)", () => {
    const { container } = render(<FileIcon nodeType="folder" color="#ff0000" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("data-icon")).toBe("Folder");
    expect(svg.getAttribute("class")).not.toContain("text-yellow-500");
    expect(svg.getAttribute("style")).toContain("rgb(255, 0, 0)");
  });

  it("renders base File icon for file without mime", () => {
    const { container } = render(<FileIcon nodeType="file" />);
    expect(iconName(container)).toBe("File");
  });

  it("renders base File icon for null mime", () => {
    const { container } = render(<FileIcon nodeType="file" mimeType={null} />);
    expect(iconName(container)).toBe("File");
  });

  it.each([
    ["image/png", "FileImage"],
    ["video/mp4", "FileVideo"],
    ["audio/mpeg", "FileAudio"],
    ["text/plain", "FileText"],
    ["application/pdf", "FileText"],
    ["application/zip", "FileArchive"],
    ["application/x-rar-compressed", "FileArchive"],
    ["application/x-7z-compressed", "FileArchive"],
    ["application/gzip", "FileArchive"],
    ["application/vnd.ms-excel", "FileSpreadsheet"],
    ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "FileSpreadsheet"],
    ["application/json", "FileCode"],
    ["application/xml", "FileCode"],
    ["text/javascript", "FileText"],
    ["application/typescript", "FileCode"],
    ["application/octet-stream", "File"],
  ])("maps mime %s to %s", (mime, expected) => {
    const { container } = render(<FileIcon nodeType="file" mimeType={mime} />);
    expect(iconName(container)).toBe(expected);
  });

  it("applies custom className", () => {
    const { container } = render(<FileIcon nodeType="file" className="custom-cls" />);
    expect(container.querySelector("svg")?.getAttribute("class")).toContain("custom-cls");
  });
});
