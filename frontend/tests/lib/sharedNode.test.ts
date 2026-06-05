import { describe, expect, it } from "vitest";
import { toNodeListItem } from "@/lib/sharedNode";
import type { SharedNodeItem } from "@/types/permissions";

const shared: SharedNodeItem = {
  id: "n1",
  owner_id: "o1",
  parent_id: null,
  name: "doc.pdf",
  node_type: "file",
  visibility: "private",
  path: "/doc.pdf",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  file_size_bytes: 100,
  file_mime_type: "application/pdf",
  permission_id: "p1",
  permission_level: "download",
  can_read: true,
  can_download: true,
  can_write: false,
  can_delete: false,
  can_share: false,
  expires_at: null,
  granted_at: "2026-01-01T00:00:00Z",
  granted_by: "o1",
  granted_by_username: "alice",
};

describe("toNodeListItem", () => {
  it("переносит метаданные узла и подставляет безопасные значения", () => {
    const node = toNodeListItem(shared);
    expect(node).toMatchObject({
      id: "n1",
      owner_id: "o1",
      name: "doc.pdf",
      node_type: "file",
      file_mime_type: "application/pdf",
      depth: 0,
      is_deleted: false,
    });
  });

  it("не содержит полей права доступа", () => {
    const node = toNodeListItem(shared) as unknown as Record<string, unknown>;
    expect(node.permission_level).toBeUndefined();
    expect(node.can_write).toBeUndefined();
  });
});
