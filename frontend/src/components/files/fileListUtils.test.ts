import { describe, it, expect } from "vitest";
import type { NodeListItem } from "@/types/nodes";
import { applyFilter, sortItems } from "./fileListUtils";

function makeItem(over: Partial<NodeListItem> = {}): NodeListItem {
  return {
    id: over.id ?? "id",
    owner_id: "owner",
    parent_id: null,
    name: over.name ?? "item",
    node_type: over.node_type ?? "file",
    visibility: "private",
    path: "/item",
    depth: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    is_deleted: false,
    file_size_bytes: over.file_size_bytes ?? null,
    file_mime_type: over.file_mime_type ?? null,
    ...over,
  };
}

describe("applyFilter", () => {
  const folder = makeItem({ id: "f", node_type: "folder", name: "Folder" });
  const image = makeItem({ id: "i", file_mime_type: "image/png" });
  const video = makeItem({ id: "v", file_mime_type: "video/mp4" });
  const audio = makeItem({ id: "a", file_mime_type: "audio/mpeg" });
  const pdf = makeItem({ id: "p", file_mime_type: "application/pdf" });
  const text = makeItem({ id: "t", file_mime_type: "text/plain" });
  const word = makeItem({ id: "w", file_mime_type: "application/msword" });
  const excel = makeItem({ id: "e", file_mime_type: "application/vnd.ms-excel" });
  const ppt = makeItem({ id: "pp", file_mime_type: "application/vnd.ms-powerpoint" });
  const officeDoc = makeItem({
    id: "od",
    file_mime_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  const zip = makeItem({ id: "z", file_mime_type: "application/zip" });
  const rar = makeItem({ id: "r", file_mime_type: "application/x-rar-compressed" });
  const sevenZip = makeItem({ id: "7", file_mime_type: "application/x-7z-compressed" });
  const gzip = makeItem({ id: "g", file_mime_type: "application/gzip" });
  const tar = makeItem({ id: "ta", file_mime_type: "application/x-tar" });
  const noMime = makeItem({ id: "n", file_mime_type: null });

  const all = [
    folder,
    image,
    video,
    audio,
    pdf,
    text,
    word,
    excel,
    ppt,
    officeDoc,
    zip,
    rar,
    sevenZip,
    gzip,
    tar,
    noMime,
  ];

  it("returns all items unchanged for 'all'", () => {
    expect(applyFilter(all, "all")).toBe(all);
  });

  it("filters folders", () => {
    expect(applyFilter(all, "folder")).toEqual([folder]);
  });

  it("filters images", () => {
    expect(applyFilter(all, "image")).toEqual([image]);
  });

  it("filters videos", () => {
    expect(applyFilter(all, "video")).toEqual([video]);
  });

  it("filters audio", () => {
    expect(applyFilter(all, "audio")).toEqual([audio]);
  });

  it("filters documents (text, pdf, office)", () => {
    expect(applyFilter(all, "document")).toEqual([pdf, text, word, excel, ppt, officeDoc]);
  });

  it("filters archives", () => {
    expect(applyFilter(all, "archive")).toEqual([zip, rar, sevenZip, gzip, tar]);
  });

  it("treats missing mime as empty string for document/archive", () => {
    const items = [makeItem({ id: "x", file_mime_type: undefined })];
    expect(applyFilter(items, "document")).toEqual([]);
    expect(applyFilter(items, "archive")).toEqual([]);
  });

  it("returns items for unknown filter value (fallthrough)", () => {
    expect(applyFilter(all, "unknown" as never)).toBe(all);
  });
});

describe("sortItems", () => {
  it("places folders before files", () => {
    const items = [
      makeItem({ id: "1", node_type: "file", name: "a" }),
      makeItem({ id: "2", node_type: "folder", name: "z" }),
    ];
    const sorted = sortItems(items);
    expect(sorted.map((i) => i.id)).toEqual(["2", "1"]);
  });

  it("sorts same-type items by name with ru locale", () => {
    const items = [
      makeItem({ id: "1", node_type: "file", name: "Бета" }),
      makeItem({ id: "2", node_type: "file", name: "Альфа" }),
    ];
    const sorted = sortItems(items);
    expect(sorted.map((i) => i.name)).toEqual(["Альфа", "Бета"]);
  });

  it("does not mutate the original array", () => {
    const items = [
      makeItem({ id: "1", node_type: "file", name: "b" }),
      makeItem({ id: "2", node_type: "folder", name: "a" }),
    ];
    const copy = [...items];
    sortItems(items);
    expect(items).toEqual(copy);
  });

  it("returns -1 branch when first is folder", () => {
    const items = [
      makeItem({ id: "1", node_type: "folder", name: "x" }),
      makeItem({ id: "2", node_type: "file", name: "x" }),
    ];
    expect(sortItems(items).map((i) => i.id)).toEqual(["1", "2"]);
  });
});
