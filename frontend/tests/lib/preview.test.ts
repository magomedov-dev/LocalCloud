import { describe, expect, it } from "vitest";
import { thumbnailSupported } from "@/lib/preview";

describe("thumbnailSupported", () => {
  it.each([
    ["image/png", true],
    ["IMAGE/JPEG", true],
    ["video/mp4", true],
    ["application/pdf", true],
    ["text/plain", false],
    ["application/json", false],
    ["application/zip", false],
    ["application/octet-stream", false],
    ["", false],
    [null, false],
    [undefined, false],
  ])("%s -> %s", (mime, expected) => {
    expect(thumbnailSupported(mime as string | null | undefined)).toBe(expected);
  });
});
