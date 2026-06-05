import { describe, it, expect, vi } from "vitest";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({ data: {} })),
  post: vi.fn(() => Promise.resolve({ data: {} })),
  put: vi.fn(() => Promise.resolve({ data: {} })),
  patch: vi.fn(() => Promise.resolve({ data: {} })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
}));
vi.mock("@/lib/api", () => ({ default: mockApi, api: mockApi }));

import * as apiBarrel from "@/api/index";

describe("api barrel", () => {
  it("re-exports all API clients", () => {
    expect(apiBarrel.authApi).toBeDefined();
    expect(apiBarrel.registrationApi).toBeDefined();
    expect(apiBarrel.usersApi).toBeDefined();
    expect(apiBarrel.quotasApi).toBeDefined();
    expect(apiBarrel.foldersApi).toBeDefined();
    expect(apiBarrel.uploadsApi).toBeDefined();
    expect(apiBarrel.nodesApi).toBeDefined();
    expect(apiBarrel.trashApi).toBeDefined();
    expect(apiBarrel.publicLinksApi).toBeDefined();
    expect(apiBarrel.permissionsApi).toBeDefined();
    expect(apiBarrel.auditApi).toBeDefined();
    expect(apiBarrel.tasksApi).toBeDefined();
    expect(apiBarrel.downloadsApi).toBeDefined();
  });
});
