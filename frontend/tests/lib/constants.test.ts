import { describe, expect, it } from "vitest";
import {
  ARCHIVE_POLL_MS,
  ARCHIVE_TIMEOUT_MS,
  MAX_CONCURRENT_UPLOADS,
  THUMBNAIL_URL_TTL_MS,
  UPLOAD_PART_SIZE,
  UPLOAD_RETRY_BASE_MS,
  UPLOAD_RETRY_MAX,
} from "@/lib/constants";

describe("constants", () => {
  it("экспортирует ожидаемые значения upload", () => {
    expect(UPLOAD_PART_SIZE).toBe(8 * 1024 * 1024);
    expect(MAX_CONCURRENT_UPLOADS).toBe(5);
    expect(UPLOAD_RETRY_MAX).toBe(4);
    expect(UPLOAD_RETRY_BASE_MS).toBe(1500);
  });

  it("экспортирует ожидаемые значения archive download", () => {
    expect(ARCHIVE_POLL_MS).toBe(2000);
    expect(ARCHIVE_TIMEOUT_MS).toBe(15 * 60 * 1000);
  });

  it("экспортирует TTL thumbnail URL", () => {
    expect(THUMBNAIL_URL_TTL_MS).toBe(12 * 60 * 1000);
  });

  it("все значения являются положительными конечными числами", () => {
    for (const v of [
      UPLOAD_PART_SIZE,
      MAX_CONCURRENT_UPLOADS,
      UPLOAD_RETRY_MAX,
      UPLOAD_RETRY_BASE_MS,
      ARCHIVE_POLL_MS,
      ARCHIVE_TIMEOUT_MS,
      THUMBNAIL_URL_TTL_MS,
    ]) {
      expect(Number.isFinite(v)).toBe(true);
      expect(v).toBeGreaterThan(0);
    }
  });
});
